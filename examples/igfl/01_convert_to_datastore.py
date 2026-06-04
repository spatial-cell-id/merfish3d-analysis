"""
Convert raw tiff igfl aberrior confocal 3D MERFISH data to qi2labdatastore.

Required user parameters for system dependent variables are at end of script.

Shepherd 2024/12 - added more NDTIFF metadata extraction for camera and binning.
Shepherd 2024/12 - refactor
Shepherd 2024/11 - rework script to accept parameters.
Shepherd 2024/08 - rework script to utilize qi2labdatastore object.
"""

from merfish3danalysis.qi2labDataStore import qi2labDataStore
from pathlib import Path
import numpy as np
import pandas as pd
from psfmodels import make_psf
from tifffile import imread
from tqdm import tqdm
from merfish3danalysis.utils.dataio import read_metadatafile
from merfish3danalysis.utils.imageprocessing import replace_hot_pixels
from itertools import compress
from typing import Optional

from tifffile import TiffFile
import xmltodict
import json 

def convert_data(
    root_path: Path,
    hot_pixel_image_path: Optional[Path] = None,
    output_path: Optional[Path] = None,
    codebook_path: Optional[Path] = None,
    channel_order_path: Optional[Path] = None,
):
    """Convert Abberior microscopy images of MERFISH experiment to qi2lab datastore. Exctract relevant info from OME-XML metadata

    Parameters
    ----------
    root_path: Path
        path to dataset
    hot_pixel_image_path: Optional[Path], default None
        path to hot pixel map. Default of `None` will set it to all zeros.
    output_path: Optional[Path], default None
        path to output directory. Default of `None` and will be created
        within the root_path
    codebook_path: Optional[Path], default None
        path to codebook. Default of `None` assumes the file is in
        the root_path.
    bit_order_path: Optional[Path], default None
        path to bit order file. This file defines what bits are present in each
        imaging round, in channel order. Default of `None` assumes
        the file is in the root_path.
    """
    assert root_path.exists(), f"{root_path} was not found."
    # load codebook
    # --------------
    if codebook_path is None:
        codebook = pd.read_csv(root_path / Path("codebook.csv"))
    else:
        codebook = pd.read_csv(codebook_path)
        
    # load sample tile to extract acquisition metadata
    root_name = root_path.stem
    raw_folder = root_path / "Raw ome tiff"
    
    sample_round_folder = raw_folder / f"{root_name}_r{(1):04d}"
    assert sample_round_folder.exists(), f"{sample_round_folder} doesn't exists."
    sample_list_tiles = list(sample_round_folder.glob("*.ome.tiff"))
    sample_img_path = sample_list_tiles[0]
    sample_ome_tif = TiffFile(sample_img_path)
    assert sample_ome_tif.is_ome, f"{sample_ome_tif} is not a OME TIF. Cannot extract metadata." 
    ome_metadata_dict = xmltodict.parse(sample_ome_tif.ome_metadata)['OME']
    description_json = ome_metadata_dict["Folder"][2]['Description']
    ome_metadata_dict["Folder"][2]['Description']= json.loads(description_json)
    with open(root_path / "ome_metadata.json", "w") as f:
        json.dump(ome_metadata_dict,f,indent=4)

    # load experiment metadata
    num_rounds = len(list(raw_folder.glob(f"{root_name}_r*"))) # TODO fetch num rounds : ex num of round folder ? or master recipe ?
    num_ch = int(ome_metadata_dict["Image"]["Pixels"]["@SizeC"])
    # num_tiles = len(sample_list_tiles)
    num_tiles = 1  
    # z_step_um = float(ome_metadata_dict["Image"]["Pixels"]["@PhysicalSizeZ"]) * 1e6
    z_step_um = float(ome_metadata_dict["Image"]["Pixels"]["@PhysicalSizeZ"]) * 1e6
    yx_pixel_um = float(ome_metadata_dict["Image"]["Pixels"]["@PhysicalSizeX"]) * 1e6 # NB : x and y resolution are slightly different in ome metadata
    voxel_size_zyx_um = [z_step_um, yx_pixel_um]
    na = float(ome_metadata_dict["Folder"][2]["Description"]["objective_lens"]["name"].split("NA")[-1].split("(")[0]) #TODO fix messy ome-xml
    ri = 1.4 # TODO get from the ome-metadata, correspond to silicon ri
    ri_sample = 1.33 #TODO estimate sample ri
    
    channel_names = [chan["@Name"] for chan in  ome_metadata_dict["Image"]["Pixels"]["Channel"]]
    em_wavelengths_um = [float(chan["@EmissionWavelength"])*1e6 for chan in  ome_metadata_dict["Image"]["Pixels"]["Channel"]]
    ex_wavelengths_um = [float(chan["@ExcitationWavelength"])*1e6 for chan in  ome_metadata_dict["Image"]["Pixels"]["Channel"]]
    
    # load decon folder 
    decon_folder = root_path / "Hyugens decon"
    
    # channel_idxs = list(range(num_ch))
    # channels_active = [True for _ in range(num_ch)]
    # channels_active[3] = False
    # channels_in_data = list(compress(channel_idxs, channels_active))
    # metadata = {}
    # metadata["num_r"] = num_rounds
    # metadata["num_xyz"] = num_tiles
    # metadata["num_ch"] = num_ch
    # metadata["z_step_um"] = z_step_um
    # metadata["yx_pixel_um"] = yx_pixel_um
    
    # load experimental order
    # -----------------------
    if channel_order_path is None:
        # df_experiment_order = pd.read_csv(root_path / Path("channel_order.csv"), index_col=0)
        df_experiment_order = pd.read_csv(root_path / Path("channel_order.csv"))
        dye_order = list(df_experiment_order.columns)
        experiment_order = df_experiment_order.values
        # experiment_order = df_experiment_order
    else:
        df_experiment_order = pd.read_csv(channel_order_path)
        dye_order = list(df_experiment_order.columns)
        experiment_order = df_experiment_order.values
        # experiment_order = df_experiment_order
    
    # Add fiducial DAPI channel
    # dye_order.insert(0,'DAPI')
    # Map dye order to channel order 
    dye_to_chan_dict = {dye_name : channel_names.index(dye_name) for dye_name in dye_order}
    
    # load stage orientation vs computer orientation parameters.
    # ----------------------------------------------------------
    # TODO figure if these values need to be changed
    stage_flipped_x = False
    stage_flipped_y = False
    image_rotated = False
    image_flipped_y = False
    image_flipped_x = False
        
        
    # generate PSFs
    # --------------
    # TODO replace psf list by a dict
    channel_psfs = []
    for dye_name in dye_order:
        psf = make_psf(
            z=51,
            nx=51,
            dxy=voxel_size_zyx_um[1],
            dz=voxel_size_zyx_um[0],
            NA=na,
            wvl=em_wavelengths_um[dye_to_chan_dict[dye_name]],
            ns=ri_sample,
            ni=ri,
            ni0=ri,
            model="vectorial",
        ).astype(np.float32)
        psf = psf / np.sum(psf, axis=(0, 1, 2))
        channel_psfs.append(psf)
    channel_psfs = np.asarray(channel_psfs, dtype=np.float32)

    # initialize datastore
    # --------------------
    if output_path is None:
        datastore_path = root_path / Path(r"qi2labdatastore")
        datastore = qi2labDataStore(datastore_path)
    else:
        datastore = qi2labDataStore(output_path)

    # populate datastore metadata
    datastore.channels_in_data = dye_order
    datastore.num_rounds = num_rounds
    datastore.codebook = codebook
    datastore.experiment_order = experiment_order
    datastore.num_tiles = num_tiles
    # TODO modify threshold value ? change criteria ? 
    if z_step_um < 0.5:
        datastore.microscope_type = "3D"
    else:
        datastore.microscope_type = "2D"
    datastore.camera_model = "aberrior igfl"
    datastore.camera = "aberrior igfl"
    datastore.tile_overlap = float(ome_metadata_dict["Folder"][2]["Description"]["region"]["tiles_overlap"])/100
    datastore.e_per_ADU = 1 # TODO necessary ? check for compatibility
    datastore.offset = 0  # TODO necessary ? check for compatibility   2**15
    datastore.na = na
    datastore.ri = ri
    datastore.binning = 1 # TODO necessary ? check for compatibility
    datastore.noise_map = None # TODO necessary ? check for compatibility
    datastore._shading_maps = None #np.ones((3, 2048, 2048), dtype=np.float32)  # TODO necessary ? check for compatibility
    datastore.channel_psfs = channel_psfs
    datastore.voxel_size_zyx_um = voxel_size_zyx_um

    # Update datastore state to note that calibrations are done
    datastore_state = datastore.datastore_state
    datastore_state.update({"Calibrations": True})
    datastore.datastore_state = datastore_state

    # # Deal with camera vs stage orientation for stage positions.
    # # This is required because we want all of the data in global world
    # # coordinates, but the camera and software may not match the stage's
    # # orientation or motion direction.
    # # TODO Get max_y and max_x
    # round_idx = 0
    # if stage_flipped_x or stage_flipped_y:
    #     for tile_idx in range(num_tiles):
    #         stage_position_path = root_path / f"{root_name}_r{(round_idx + 1):04d}_tile{tile_idx:04d}_stage_positions.csv"
    #         stage_positions = read_metadatafile(stage_position_path)
    #         stage_x = np.round(float(stage_positions["stage_x"]), 2)
    #         stage_y = np.round(float(stage_positions["stage_y"]), 2)
    #         if tile_idx == 0:
    #             max_y = stage_y
    #             max_x = stage_x
    #         else:
    #             if max_y < stage_y:
    #                 max_y = stage_y
    #             if max_x < stage_x:
    #                 max_x = stage_x
                    
    # TODO : fix memory issue when tiles are too big. For now crop tiles in Z
    z_size_crop = 100   
    # Fetch expected image shape (CZYX)
    correct_shape = (int(ome_metadata_dict["Image"]["Pixels"]["@SizeC"]), 
                     z_size_crop,
                     int(ome_metadata_dict["Image"]["Pixels"]["@SizeY"]),
                     int(ome_metadata_dict["Image"]["Pixels"]["@SizeX"]))
    # int(ome_metadata_dict["Image"]["Pixels"]["@SizeZ"]), 

    # Loop over data and create datastore.
    for round_idx in tqdm(range(num_rounds), desc="rounds"):
        round_folder = raw_folder / f"{root_name}_r{(round_idx + 1):04d}"
        decon_round_folder = decon_folder / f"{root_name}_r{(round_idx + 1):04d} decon"
        assert round_folder.exists()
        for tile_idx in tqdm(range(num_tiles), desc="tile", leave=False):
            # initialize datastore tile
            # this creates the directory structure and links fiducial rounds <-> readout bits
            if round_idx == 0:
                datastore.initialize_tile(tile_idx)

            # load raw image
            image_path = round_folder / f"{root_name}_r{(round_idx + 1):04d}_tile{(tile_idx):04d}.ome.tiff"
            assert  image_path.exists()
            # load ome metadata
            image_ome_tif = TiffFile(image_path)
            assert image_ome_tif.is_ome, f"{image_ome_tif} is not a OME TIF. Cannot extract metadata." 
            ome_metadata_dict = xmltodict.parse(image_ome_tif.ome_metadata)['OME']
            description_json = ome_metadata_dict["Folder"][2]['Description']
            ome_metadata_dict["Folder"][2]['Description']= json.loads(description_json)
            
            # load decon image channel by channel and concatenate them
            decon_image_ch_paths =  list(decon_round_folder.glob(f"{root_name}_r{(round_idx + 1):04d}_tile{(tile_idx):04d}_decon_ch*.tif"))
            decon_image_ch_paths.sort()
            assert len(decon_image_ch_paths)==num_ch, f"Found {len(decon_image_ch_paths)} channels for decon image \
                {root_name}_r{(round_idx + 1):04d}_tile{(tile_idx):04d}, it doesn't match expected number of channels which is {num_ch}."
            # print([path.stem.split("_")[-1] for path in decon_image_ch_paths])
            decon_image = np.stack([imread(ch_img_path)[:z_size_crop,...] for ch_img_path in decon_image_ch_paths], axis=0)
            
            # load raw data and make sure it is the right shape. If not, write
            # zeros for this round/stage position.
            # raw_image = imread(image_path)[:,:z_size_crop,...]
            # if datastore.camera == "orcav3":
            #     raw_image = np.swapaxes(raw_image, 0, 1)
            #     if tile_idx == 0 and round_idx == 0:
            #         correct_shape = raw_image.shape
            # elif datastore.camera == "flir":
            #     if tile_idx == 0 and round_idx == 0:
            #         correct_shape = raw_image.shape
            if decon_image is None or decon_image.shape != correct_shape:
                print("\nround=" + str(round_idx + 1) + "; tile=" + str(tile_idx + 1))
                print("Found shape: " + str(decon_image.shape))
                print("Correct shape: " + str(correct_shape))
                print("Replacing data with zeros.\n")
                decon_image = np.zeros(correct_shape, dtype=np.uint16)

            # Correct if camera is rotated wrt to stage
            if image_rotated:
                decon_image = np.rot90(decon_image, k=-1, axes=(3, 2))

            # Correct if camera is flipped in y wrt to stage
            if image_flipped_y:
                decon_image = np.flip(decon_image, axis=2)

            # Correct if camera is flipped in x wrt to stage
            if image_flipped_x:
                decon_image = np.flip(decon_image, axis=3)

            # Correct for known camera gain and offset
            decon_image = (decon_image - datastore.offset) * datastore.e_per_ADU
            decon_image[decon_image < 0.0] = 0.0
            decon_image = decon_image.astype(np.uint16)
            gain_corrected = True

            # # Correct for known hot pixel map
            # if datastore.camera == "flir":
            #     raw_image = replace_hot_pixels(datastore.noise_map, raw_image)
            #     raw_image = replace_hot_pixels(
            #         np.max(raw_image, axis=0), raw_image, threshold=100
            #     )
            #     hot_pixel_corrected = True
            # else:
            #     hot_pixel_corrected = False

            # get stage position from ome metadata
            stage_x = np.array([np.round(float(plane["@PositionX"])*1e6, 2) for plane in ome_metadata_dict["Image"]["Pixels"]["Plane"]]).mean()
            stage_y = np.array([np.round(float(plane["@PositionY"])*1e6, 2) for plane in ome_metadata_dict["Image"]["Pixels"]["Plane"]]).mean()
            stage_z = np.array([np.round(float(plane["@PositionZ"])*1e6, 2) for plane in ome_metadata_dict["Image"]["Pixels"]["Plane"]])[0]
            
            # # correct for stage direction reversed wrt to global coordinates
            # if stage_flipped_x or stage_flipped_y:
            #     if stage_flipped_y:
            #         corrected_y = max_y - stage_y
            #     else:
            #         corrected_y = stage_y
            #     if stage_flipped_x:
            #         corrected_x = max_x - stage_x
            #     else:
            #         corrected_x = stage_x
            # else:
            #     corrected_y = stage_y
            #     corrected_x = stage_x
            
            stage_pos_zyx_um = np.asarray(
                [stage_z, stage_y, stage_x], dtype=np.float32
            )
            # save local tile pos
            affine_zyx_px = np.eye(4)
            datastore.save_local_stage_position_zyx_um(
                stage_pos_zyx_um, affine_zyx_px, tile=tile_idx, round=round_idx
            )
            
            # write fidicual data (ch_idx = -1) and metadata
            datastore.save_local_corrected_image(
                np.squeeze(decon_image[dye_to_chan_dict['DAPI'], :]).astype(np.uint16),
                tile=tile_idx,
                psf_idx=dye_order.index('DAPI'),
                gain_correction=gain_corrected,
                hotpixel_correction=False,
                shading_correction=False,
                round=round_idx,
            )
            datastore.save_local_wavelengths_um(
                (ex_wavelengths_um[dye_to_chan_dict['DAPI']], em_wavelengths_um[dye_to_chan_dict['DAPI']]),
                tile=tile_idx,
                round=round_idx,
            )
            
            # write readout channels and metadata
            for dye_name in tqdm(dye_order[1:], desc="bit channels", leave=False): 
                datastore.save_local_corrected_image(
                    np.squeeze(decon_image[dye_to_chan_dict[dye_name], :]).astype(np.uint16),
                    tile=tile_idx,
                    psf_idx=dye_order.index(dye_name),
                    gain_correction=gain_corrected,
                    hotpixel_correction=False,
                    shading_correction=False,
                    bit=int(experiment_order[round_idx, dye_order.index(dye_name)])-1,
                )
                datastore.save_local_wavelengths_um(
                    (ex_wavelengths_um[dye_to_chan_dict[dye_name]], em_wavelengths_um[dye_to_chan_dict[dye_name]]),
                    tile=tile_idx,
                    bit=int(experiment_order[round_idx, dye_order.index(dye_name)])-1,
                )

    datastore_state = datastore.datastore_state
    datastore_state.update({"Corrected": True})
    datastore.datastore_state = datastore_state

if __name__ == "__main__":
    root_path = Path(r"/home/hblanc01/Data/20250718 DH_Merfish_Disc_2")
    convert_data(
        root_path=root_path,
    )

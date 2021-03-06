#%%
"""
Example script to register two volumes with VoxelMorph models

Please make sure to use trained models appropriately. 
Let's say we have a model trained to register subject (moving) to atlas (fixed)
One could run:

python register.py --gpu 0 /path/to/test_vol.nii.gz /path/to/atlas_norm.nii.gz --out_img /path/to/out.nii.gz --model_file ../models/cvpr2018_vm2_cc.h5 
"""

#%%
# py imports
import os
import sys
from argparse import ArgumentParser

# third party
import tensorflow as tf
import numpy as np
import keras
from keras.backend.tensorflow_backend import set_session
from scipy.interpolate import interpn

#%%
# project
sys.path.append('/home/jdram/voxelmorph/src')
import networks, losses
sys.path.append('/home/jdram/voxelmorph/ext/neuron')
import neuron.layers as nrn_layers

#%%

def register(gpu_id, mov, fix, model_file, out_img, out_warp):
    """
    register moving and fixed. 
    """  
    #assert model_file, "A model file is necessary"
    #assert out_img or out_warp, "output image or warp file needs to be specified"

    # GPU handling
    if gpu_id is not None:
        gpu = '/gpu:' + str(gpu_id)
        os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu_id)
        config = tf.ConfigProto()
        config.gpu_options.allow_growth = True
        config.allow_soft_placement = True
        set_session(tf.Session(config=config))
    else:
        gpu = '/cpu:0'

    # load data
    #mov_nii = nib.load(moving)
    #mov = mov_nii.get_data()[np.newaxis, ..., np.newaxis]
    #fix_nii = nib.load(fixed)
    #fix = fix_nii.get_data()[np.newaxis, ..., np.newaxis]

    with tf.device(gpu):
        # load model
        loss_class = losses.Miccai2018(0.02, 10, flow_vol_shape=[64])
        custom_objects = {'SpatialTransformer': nrn_layers.SpatialTransformer,
                 'VecInt': nrn_layers.VecInt,
                 'Sample': networks.Sample,
                 'Rescale': networks.RescaleDouble,
                 'Resize': networks.ResizeDouble,
                 'Negate': networks.Negate,
                 'recon_loss': loss_class.recon_loss, # values shouldn't matter
                 'kl_loss': loss_class.kl_loss        # values shouldn't matter
                 }


        net = keras.models.load_model(model_file, custom_objects=custom_objects)
        
        # register
        [moved, warp] = net.predict([mov, fix])

    return moved, warp

#%%
vm_dir = '/home/jdram/voxelmorph/'
base    = np.load(os.path.join(vm_dir, "data","ts12_dan_a88_fin_o_trim_adpc_002661.npy"))
monitor = np.load(os.path.join(vm_dir, "data","ts12_dan_a05_fin_o_trim_adpc_002682.npy"))

r = 2950
moving = monitor[r:r+1,:,:,:,:]
fixed  =    base[r:r+1,:,:,:,:]

#%%
moved, warped = register(5, moving, fixed, "/home/jdram/voxelmorph/models/backup/miccai_full_301.h5", None, None)

#%%

np.save("moving.npy",moving)
np.save("fixed.npy",fixed)
np.save("moved.npy",moved)
np.save("warped.npy",warped)

moved = np.load("moved.npy")
moving = np.load("moving.npy")
fixed = np.load("fixed.npy")
warped = np.load("warped.npy")

"""
train atlas-based alignment with MICCAI2018 version of VoxelMorph, 
specifically adding uncertainty estimation and diffeomorphic transforms.
"""

# python imports
import os
import glob
import sys
import random
from argparse import ArgumentParser

# third-party imports
import tensorflow as tf
import numpy as np
from keras.backend.tensorflow_backend import set_session
from keras.optimizers import Adam
from keras.callbacks import ModelCheckpoint, CSVLogger, TerminateOnNaN, ReduceLROnPlateau, EarlyStopping

# project imports
import datagenerators
import networks
import losses

vm_dir = '/home/jdram/voxelmorph/'
sys.path.append(os.path.join(vm_dir, 'ext', 'neuron'))
import neuron.callbacks as nrn_gen

# export PYTHONPATH=$PYTHONPATH:/home/jdram/voxelmorph/ext/neuron/:/home/jdram/voxelmorph/ext/pynd-lib/:/home/jdram/voxelmorph/ext/pytools-lib/

def train(data_dir,
          atlas_file,
          model_dir,
          gpu_id,
          lr,
          nb_epochs,
          prior_lambda,
          image_sigma,
          steps_per_epoch,
          batch_size,
          load_model_file,
          bidir,
          bool_cc,
          initial_epoch=0):
    """
    model training function
    :param data_dir: folder with npz files for each subject.
    :param atlas_file: atlas filename. So far we support npz file with a 'vol' variable
    :param model_dir: model folder to save to
    :param gpu_id: integer specifying the gpu to use
    :param lr: learning rate
    :param nb_epochs: number of training iterations
    :param prior_lambda: the prior_lambda, the scalar in front of the smoothing laplacian, in MICCAI paper
    :param image_sigma: the image sigma in MICCAI paper
    :param steps_per_epoch: frequency with which to save models
    :param batch_size: Optional, default of 1. can be larger, depends on GPU memory and volume size
    :param load_model_file: optional h5 model file to initialize with
    :param bidir: logical whether to use bidirectional cost function
    :param bool_cc: Train CC or MICCAI version
    """
    
    # load atlas from provided files. The atlas we used is 160x192x224.
    #atlas_vol = np.load(atlas_file)['vol'][np.newaxis, ..., np.newaxis]
    vm_dir = '/home/jdram/voxelmorph/'
    base    = np.load(os.path.join(vm_dir, "data","ts12_dan_a88_fin_o_trim_adpc_002661_256.npy"))
    monitor = np.load(os.path.join(vm_dir, "data","ts12_dan_a05_fin_o_trim_adpc_002682_256.npy"))
    #base    = np.load(os.path.join(vm_dir, "data","ts12_dan_a88_fin_o_trim_adpc_002661_abs.npy"))
    #monitor = np.load(os.path.join(vm_dir, "data","ts12_dan_a05_fin_o_trim_adpc_002682_abs.npy"))
    
    #vol_size = (64, 64, 64)
    vol_size = (64, 64, 256-64)
    #vol_size = (128, 128, 256)
    
    # prepare data files
    # for the CVPR and MICCAI papers, we have data arranged in train/validate/test folders
    # inside each folder is a /vols/ and a /asegs/ folder with the volumes
    # and segmentations. All of our papers use npz formated data.
    #train_vol_names = glob.glob(os.path.join(data_dir, '*.npy'))
    #random.shuffle(train_vol_names)  # shuffle volume list
    #assert len(train_vol_names) > 0, "Could not find any training data"

    # Diffeomorphic network architecture used in MICCAI 2018 paper
    nf_enc = [32,64,64,64]
    nf_dec = [64,64,64,64,32,3]

    # prepare model folder
    if not os.path.isdir(model_dir):
        os.mkdir(model_dir)
    tf.reset_default_graph()

    if bool_cc:
        pre_net = "cc_"
    else:
        if bidir:
            pre_net = "miccai_bidir_"
        else:
            pre_net = "miccai_"


    # gpu handling
    gpu = '/device:GPU:%d' % int(gpu_id) # gpu_id
    os.environ["CUDA_VISIBLE_DEVICES"] = gpu_id
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    config.allow_soft_placement = True
    set_session(tf.Session(config=config))

    # prepare the model
    with tf.device(gpu):
        # prepare the model
        # in the CVPR layout, the model takes in [image_1, image_2] and outputs [warped_image_1, flow]
        # in the experiments, we use image_2 as atlas
        if bool_cc:
            model = networks.cvpr2018_net(vol_size, nf_enc, nf_dec)
        else:
            model = networks.miccai2018_net(vol_size, nf_enc, nf_dec, bidir=bidir, vel_resize=.5)  


        # load initial weights
        if load_model_file is not None and load_model_file != "":
            print('loading', load_model_file)
            model.load_weights(load_model_file)

        # save first iteration
        model.save(os.path.join(model_dir, f'{pre_net}{initial_epoch:02d}.h5'))
        model.summary()

        if bool_cc:
            model_losses = [losses.NCC().loss, losses.Grad('l2').loss]
            loss_weights = [1.0, 0.01]  # recommend 1.0 for ncc, 0.01 for mse
        else:
            flow_vol_shape = model.outputs[-1].shape[1:-1]
            loss_class = losses.Miccai2018(image_sigma, prior_lambda, flow_vol_shape=flow_vol_shape)
            if bidir:
                model_losses = [loss_class.recon_loss, loss_class.recon_loss, loss_class.kl_loss]
                loss_weights = [0.5, 0.5, 1]
            else:
                model_losses = [loss_class.recon_loss, loss_class.kl_loss]
                loss_weights = [1, 1]

    segy_gen = datagenerators.segy_gen(base, monitor, batch_size=batch_size)

    # prepare callbacks
    save_file_name = os.path.join(model_dir, pre_net+'{epoch:02d}.h5')

    with tf.device(gpu):
        # fit generator
        save_callback = ModelCheckpoint(save_file_name, period=5)
        csv_cb = CSVLogger(f'{pre_net}log.csv')
        nan_cb = TerminateOnNaN()
        rlr_cb = ReduceLROnPlateau(monitor='loss', verbose=1)
        els_cb = EarlyStopping(monitor='loss', patience=15, verbose=1, restore_best_weights=True)
        cbs = [save_callback, csv_cb, nan_cb, rlr_cb, els_cb]
        mg_model = model

        # compile
        mg_model.compile(optimizer=Adam(lr=lr), loss=model_losses, loss_weights=loss_weights)


            
        mg_model.fit([base, monitor],[monitor, np.zeros_like(base)], 
                     initial_epoch=initial_epoch,
                     batch_size=8,
                     epochs=nb_epochs,
                     callbacks=cbs,
                     #steps_per_epoch=steps_per_epoch,
                     verbose=1)


if __name__ == "__main__":
    parser = ArgumentParser()

    parser.add_argument("--data_dir", type=str, default='/home/jdram/voxelmorph/data',
                        help="data folder")

    parser.add_argument("--atlas_file", type=str,
                        dest="atlas_file", default='/home/jdram/voxelmorph/data/atlas_norm.npz',
                        help="atlas file")
    parser.add_argument("--model_dir", type=str,
                        dest="model_dir", default='/home/jdram/voxelmorph/models/',
                        help="models folder")
    parser.add_argument("--gpu", type=str, default="6",
                        dest="gpu_id", help="gpu id number")
    parser.add_argument("--lr", type=float,
                        dest="lr", default=1e-4, help="learning rate")
    parser.add_argument("--epochs", type=int,
                        dest="nb_epochs", default=350,
                        help="number of iterations")
    parser.add_argument("--prior_lambda", type=float,
                        dest="prior_lambda", default=10,
                        help="prior_lambda regularization parameter")
    parser.add_argument("--image_sigma", type=float,
                        dest="image_sigma", default=0.02,
                        help="image noise parameter")
    parser.add_argument("--steps_per_epoch", type=int,
                        dest="steps_per_epoch", default=100,
                        help="frequency of model saves")
    parser.add_argument("--batch_size", type=int,
                        dest="batch_size", default=1,
                        help="batch_size")
    parser.add_argument("--load_model_file", type=str,
                        dest="load_model_file",
                        help="optional h5 model file to initialize with")
    parser.add_argument("--bidir", type=int,
                        dest="bidir", default=0,
                        help="whether to use bidirectional cost function")
    parser.add_argument("--initial_epoch", type=int,
                        dest="initial_epoch", default=0,
                        help="first epoch")
    parser.add_argument("--cc", type=bool,
                        dest="bool_cc", default=False,
                        help="Train MICCAI diffeomorphism version or CC.")

    args = parser.parse_args()
    train(**vars(args))

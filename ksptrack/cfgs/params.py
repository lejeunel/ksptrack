import os
import configargparse
from os.path import join as pjoin

seq_type_dict = {
    'Tweezer': ['Dataset00', 'Dataset01', 'Dataset02', 'Dataset03'],
    'Brain': ['Dataset30', 'Dataset31', 'Dataset32', 'Dataset33'],
    'Slitlamp': ['Dataset20', 'Dataset21', 'Dataset22', 'Dataset23'],
    'Cochlea': ['Dataset10', 'Dataset11', 'Dataset12', 'Dataset13']
}


def datasetdir_to_type(dir_):
    """ Get sequence type from directory name
    """

    if ((dir_ == 'Dataset00') or (dir_ == 'Dataset01') or (dir_ == 'Dataset02')
            or (dir_ == 'Dataset03')):
        seq_type = 'Tweezer'
    elif ((dir_ == 'Dataset30') or (dir_ == 'Dataset31')
          or (dir_ == 'Dataset32') or (dir_ == 'Dataset33')):
        seq_type = 'Brain'
    elif ((dir_ == 'Dataset20') or (dir_ == 'Dataset21')
          or (dir_ == 'Dataset22') or (dir_ == 'Dataset23')):
        seq_type = 'Slitlamp'
    elif ((dir_ == 'Dataset10') or (dir_ == 'Dataset11')
          or (dir_ == 'Dataset12') or (dir_ == 'Dataset13')):
        seq_type = 'Cochlea'
    else:
        seq_type = 'Unknown'

    return seq_type


def get_params(path='cfgs'):
    """ Builds default configuration
    """
    p = configargparse.ArgParser(
        config_file_parser_class=configargparse.YAMLConfigFileParser,
        default_config_files=[
            pjoin(path, 'default.yaml'),
            pjoin(path, 'feat.yaml')
        ])

    p.add('-v', help='verbose', action='store_true')

    #Paths, dirs, names ...
    p.add('--locs-dir')
    p.add('--truth-dir')
    p.add('--exp-name')
    p.add('--frame-prefix')
    p.add('--precomp-dir')
    p.add('--precomp-desc-path')
    p.add('--frame-dir')
    p.add('--frame-extension')
    p.add('--csv-fname')
    p.add('--feats-dir')

    p.add('--use-hoof', type=bool, default=True)
    p.add('--hoof-tau-u', type=float)
    p.add('--hoof-n-bins', type=int)

    #Superpixel segmentation
    p.add('--sp-labels-fname', type=str)
    p.add('--slic-compactness', type=float)
    p.add('--slic-size', type=float)
    p.add('--slic-n-sp', type=int)
    p.add('--slic-rel-size', type=float)

    # Superpixel transitions
    p.add('--sp-trans-init-mode')
    p.add('--sp-trans-init-radius', type=float)

    #Optical flow
    p.add('--oflow-alpha', type=float)
    p.add('--oflow-ratio', type=float)
    p.add('--oflow-min-width', type=float)
    p.add('--oflow-outer-iters', type=int)
    p.add('--oflow-inner-iters', type=int)
    p.add('--oflow-sor-iters', type=int)

    p.add('--n-iters-ksp', type=int)

    p.add('--monitor-score', default=False, action='store_true')

    # Bagging---------------
    p.add('--bag-t', type=int)
    p.add('--bag-n-bins', type=int)
    p.add('--bag-n-feats', type=float)
    p.add('--bag-max-samples', type=int)
    p.add('--bag-max-depth', type=int)
    p.add('--bag-jobs', type=int)
    #-----------------------

    # Metric learning
    p.add('--n-comp-pca', type=int)
    p.add('--lfda-k', type=int)
    p.add('--lfda-dim', type=int)
    p.add('--ml-n-samps', type=int)
    p.add('--ml-up-thr', type=float)
    p.add('--ml-sigma', type=float)
    p.add('--ml-down-thr', type=float)
    p.add('--ml-embedding', type=str)
    p.add('--pca', default=False, action='store_true')

    #Graph parameters
    p.add('--norm-neighbor', type=float)
    p.add('--norm-neighbor-in', type=float)

    p.add('--pm-thr', type=float)
    p.add('--thr-entrance', type=float)
    p.add('--n-iter-ksp', type=float)

    # features
    p.add('--feat-path')
    p.add('--feats-mode', type=str)
    p.add('--feat-extr-algorithm')
    p.add('--feat-feats-upsamp-size', type=int)
    p.add('--feat-n-epochs', type=int)
    p.add('--feat-loss')
    p.add('--feat-validation-split', type=float)
    p.add('--feat-data-gaussian-noise-std', type=float)
    p.add('--feat-data-rot-range', type=float)
    p.add('--feat-data-width-shift', type=float)
    p.add('--feat-data-height-shift', type=float)
    p.add('--feat-data-shear-range', type=float)
    p.add('--feat-data-someof', type=float)
    p.add('--feat-interp-n-jobs', type=int)

    p.add('--feat-sgd-learning-rate', type=float)
    p.add('--feat-sgd-learning-rate-power', type=float)
    p.add('--feat-sgd-momentum', type=float)
    p.add('--feat-sgd-decay', type=float)

    p.add('--feat-gaze-gaussian-std', type=int)

    p.add('--feat-in-shape', type=int)
    p.add('--batch-size', type=int)
    p.add('--cuda', default=False, action='store_true')

    p.add('--feat-n-workers', type=int)

    p.add('--feat-locs-gaussian-std', type=float)

    p.add('--gc-gamma-range', nargs='+', default=[0.2, 0.6])
    p.add('--gc-gamma-step', default=0.1)
    p.add('--gc-lambda-range', nargs='+', default=[20, 60])
    p.add('--gc-lambda-step', default=5)
    p.add('--gc-sigma', type=float, default=None)

    return p

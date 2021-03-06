from ksptrack import iterative_ksp
from ksptrack.cfgs import params
from os.path import join as pjoin
from sklearn.model_selection import ParameterGrid
import os


if __name__ == "__main__":

    p = params.get_params('../cfgs')

    p.add('--out-path', required=True)
    p.add('--root-path', required=True)
    p.add('--siam-run-root', default='')
    p.add('--siam-cp-name', default='')
    p.add('--sets', nargs='+', required=True)

    cfg = p.parse_args()

    cfg.sets = ['Dataset{}'.format(set_) for set_ in cfg.sets]

    for i, dset in enumerate(cfg.sets):
        cfg.in_path = pjoin(cfg.root_path, 'data/medical-labeling', dset)
        cfg.out_path = pjoin(cfg.root_path, 'runs/ksptrack', dset)

        if(cfg.siam_run_root):
            cfg.siam_path = pjoin(cfg.siam_run_root, dset, 'checkpoints',
                                  cfg.siam_cp_name)
        else:
            cfg.siam_path = ''

        cfg.exp_name = 'transexp_{}'.format(
            cfg.siam_cp_name)
        iterative_ksp.main(cfg)

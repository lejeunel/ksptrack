import os
import numpy as np
import matplotlib.pyplot as plt
import pickle as pk
import progressbar
from skimage import (color, io, segmentation)
from sklearn import (mixture, metrics, preprocessing, decomposition)
from scipy import (ndimage)
import glob, itertools
import logging
import pyflow

class OpticalFlowExtractor:

    def __init__(self,
                 save_path,
                 alpha=0.012,
                 ratio=0.75,
                 minWidth=50.,
                 nOuterFPIterations=7.,
                 nInnerFPIterations=1.,
                 nSORIterations=30.):

        self.logger = logging.getLogger('OpticalFlowExtractor')


        self.alpha = alpha
        self.ratio = ratio
        self.minWidth = minWidth
        self.nOuterFPIterations = nOuterFPIterations
        self.nInnerFPIterations = nInnerFPIterations
        self.nSORIterations = nSORIterations

    def extract(self,
                im_paths,
                save_path):

        self.logger.info('Got {} images'.format(len(im_paths)))
        flows_bvx = []
        flows_bvy = []
        flows_fvx = []
        flows_fvy = []

        out_path = os.path.join(save_path, 'flows.npz')

        if(os.path.isfile(out_path)):
            self.logger.info("""Output file {} exists. Delete it
                    or change output path """.format(out_path))
        else:
            self.logger.info('Precomputing the optical flows...')
            for f in np.arange(1, len(im_paths)):
                self.logger.info('{}/{}'.format(f, len(im_paths)))
                im1 = io.imread(im_paths[f-1]).astype(float) / 255.
                im2 = io.imread(im_paths[f]).astype(float) / 255.
                fvx, fvy, _ = pyflow.coarse2fine_flow(im1,
                                                      im2,
                                                      self.alpha,
                                                      self.ratio,
                                                      self.minWidth,
                                                      self.nOuterFPIterations,
                                                      self.nInnerFPIterations,
                                                      self.nSORIterations,
                                                      0)
                bvx, bvy, _ = pyflow.coarse2fine_flow(im2,
                                                      im1,
                                                      self.alpha,
                                                      self.ratio,
                                                      self.minWidth,
                                                      self.nOuterFPIterations,
                                                      self.nInnerFPIterations,
                                                      self.nSORIterations,
                                                      0)
                flows_bvx.append(bvx.astype(np.float32))
                flows_bvy.append(bvy.astype(np.float32))
                flows_fvx.append(fvx.astype(np.float32))
                flows_fvy.append(fvy.astype(np.float32))

            flows_bvx = np.asarray(flows_bvx).transpose(1, 2, 0)
            flows_bvy = np.asarray(flows_bvy).transpose(1, 2, 0)
            flows_fvx = np.asarray(flows_fvx).transpose(1, 2, 0)
            flows_fvy = np.asarray(flows_fvy).transpose(1, 2, 0)
            self.logger.info('Optical flow calculations done')

            self.logger.info('Saving optical flows to {}'.format(out_path))

            data = dict()
            data['bvx'] = flows_bvx
            data['bvy'] = flows_bvy
            data['fvx'] = flows_fvx
            data['fvy'] = flows_fvy
            np.savez(out_path, **data)

            self.logger.info('Done.')


    def flows_mat_to_np(self):

        self.logger.info('Converting MATLAB flows to Numpy')
        flows_mat_path = sorted(glob.glob(os.path.join(self.conf.dataInRoot, self.conf.dataSetDir,self.conf.frameDir,'TSP_flows','*flow.mat')))

        flows_mat = [io.loadmat(flows_mat_path[i]) for i in range(len(flows_mat_path))]
        flows_bvx = [flows_mat[i]['flow'][0][0][0] for i in range(len(flows_mat))]
        flows_bvy = [flows_mat[i]['flow'][0][0][1] for i in range(len(flows_mat))]
        flows_fvx = [flows_mat[i]['flow'][0][0][2] for i in range(len(flows_mat))]
        flows_fvy = [flows_mat[i]['flow'][0][0][3] for i in range(len(flows_mat))]

        flows_np = dict()
        flows_np['bvx'] = np.asarray(flows_bvx).transpose(1,2,0)
        flows_np['bvy'] = np.asarray(flows_bvy).transpose(1,2,0)
        flows_np['fvx'] = np.asarray(flows_fvx).transpose(1,2,0)
        flows_np['fvy'] = np.asarray(flows_fvy).transpose(1,2,0)

        file_out = os.path.join(self.conf.precomp_desc_path,'flows.npz')
        self.logger.info('Saving optical flows to: ' + file_out)
        np.savez(file_out, **flows_np)

        return flows_np

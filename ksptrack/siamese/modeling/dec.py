import torch
import torch.nn as nn
from ksptrack.siamese.modeling.cluster import ClusterAssignment
from ksptrack.models.deeplab_resnet import DeepLabv3_plus
from ksptrack.models.deeplab import DeepLabv3Plus
from ksptrack.siamese import utils as utls
import numpy as np
from torchvision.ops import RoIPool
import torch.nn.functional as F


class SuperpixelPooling(nn.Module):
    """
    Given a RAG containing superpixel labels, this layer
    randomly samples couples of connected feature vector
    """
    def __init__(self, use_max=False):

        super(SuperpixelPooling, self).__init__()

        self.use_max = use_max
        if (use_max):
            self.pooling = lambda x: torch.max(x, dim=1)
        else:
            self.pooling = lambda x: torch.mean(x, dim=1)


    def pool(self, x, dim):
        if(self.use_max):
            return x.max(dim=dim)[0]

        return x.mean(dim=dim)

    def forward(self, x, label_maps):

        X = []

        for i, (x_, labels) in enumerate(zip(x, label_maps)):
            X_ = [self.pooling(x_[:, labels[0, ...] == l])
                      for l in torch.unique(labels[0, ...])]
            X.append(torch.stack(X_))

        return X

class RoIPooling(nn.Module):
    """
    Given a RAG containing superpixel labels, this layer
    randomly samples couples of connected feature vector
    """
    def __init__(self, output_size, spatial_scale=1.0, use_max=False):

        super(RoIPooling, self).__init__()

        self.output_size = output_size
        self.spatial_scale = spatial_scale

        self.roi_pool = RoIPool(output_size, spatial_scale)
        self.use_max = use_max
        if (use_max):
            self.pooling = lambda x: torch.max(x, dim=1)
        else:
            self.pooling = lambda x: torch.mean(x, dim=1)

    def pool(self, x, dim):
        if(self.use_max):
            return x.max(dim=dim)[0]

        return x.mean(dim=dim)

    def forward(self, x, rois):

        X = self.roi_pool(x, rois)
        X = X.squeeze()

        return X

class DEC(nn.Module):
    def __init__(self,
                 autoencoder,
                 cluster_number: int,
                 roi_size=1,
                 roi_scale=1.0,
                 alpha: float = 1.0,
                 use_locations=False):
        """
        Module which holds all the moving parts of the DEC algorithm, as described in
        Xie/Girshick/Farhadi; this includes the AutoEncoder stage and the ClusterAssignment stage.

        :param cluster_number: number of clusters
        :param embedding_dimension: embedding dimension, input to the encoder
        :param hidden_dimension: hidden dimension, output of the encoder
        :param autoencoder: autoencoder to use
        :param alpha: parameter representing the degrees of freedom in the t-distribution, default 1.0
        """

        super(DEC, self).__init__()
        self.autoencoder = autoencoder
        self.cluster_number = cluster_number
        self.alpha = alpha

        self.use_locations = use_locations

        self.roi_pool = RoIPooling((roi_size, roi_size), roi_scale)

        embedding_dims = self.autoencoder.aspp_out_dims
        self.assignment = ClusterAssignment(cluster_number,
                                            embedding_dims,
                                            alpha)

    def grad_linears(self, switch):
        for param in self.linear1.parameters():
            param.requires_grad = switch
        for param in self.linear2.parameters():
            param.requires_grad = switch

    def grad_dec(self, switch):
        for param in self.autoencoder.parameters():
            param.requires_grad = switch
        for param in self.assignment.parameters():
            param.requires_grad = switch


    def forward(self, data):
        """
        Compute the cluster assignment using the ClusterAssignment after running the batch
        through the encoder part of the associated AutoEncoder module.

        :param batch: [batch size, embedding dimension] FloatTensor
        :return: [batch size, number of clusters] FloatTensor
        """

        res = self.autoencoder(data['image'])
        pooled_reduced_feats = self.roi_pool(res['reduced_feats'], data['bboxes'])
        pooled_aspp_feats = self.roi_pool(res['aspp_feats'], data['bboxes'])
        clusters = self.assignment(pooled_reduced_feats)

        res.update({'clusters': clusters,
                    'pooled_reduced_feats': pooled_reduced_feats,
                    'pooled_aspp_feats': pooled_aspp_feats})

        return res

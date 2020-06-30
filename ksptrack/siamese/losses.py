from torch import nn
import numpy as np
import torch
import networkx as nx
import itertools
import random
import torch.nn.functional as F
from skimage import io
import os
from ksptrack.SegLoss.losses_pytorch.dice_loss import SoftDiceLoss


def get_edges_probas(probas, edges_nn, thrs=[0.6, 0.8], clusters=None):

    edges = {'sim': [], 'disim': []}

    # get edges with both nodes in positive or negative segment
    edges_mask_sim = (probas[edges_nn[:, 0]] >=
                      thrs[1]) * (probas[edges_nn[:, 1]] >= thrs[1])
    edges_mask_sim += (probas[edges_nn[:, 0]] <
                       thrs[0]) * (probas[edges_nn[:, 1]] < thrs[0])
    if (clusters is not None):
        edges_mask_sim *= (clusters[edges_nn[:, 1]].argmax(
            dim=1) == clusters[edges_nn[:, 0]].argmax(dim=1))
    edges_sim = edges_nn[edges_mask_sim, :]

    sim_probas = torch.ones(edges_sim.shape[0]).to(probas).float()
    edges_sim = [edges_sim, sim_probas]
    edges['sim'] = edges_sim

    # get edges with one node > thr[1] and other < thr[0]
    edges_mask_disim_0 = probas[edges_nn[:, 0]] >= thrs[1]
    edges_mask_disim_0 *= probas[edges_nn[:, 1]] < thrs[0]
    edges_mask_disim_1 = probas[edges_nn[:, 1]] >= thrs[1]
    edges_mask_disim_1 *= probas[edges_nn[:, 0]] < thrs[0]
    edges_mask_disim = edges_mask_disim_0 + edges_mask_disim_1
    if (clusters is not None):
        edges_mask_disim *= (clusters[edges_nn[:, 1]].argmax(dim=1) !=
                             clusters[edges_nn[:, 0]].argmax(dim=1))
    edges_disim = edges_nn[edges_mask_disim, :]

    disim_probas = torch.zeros(edges_disim.shape[0]).to(probas).float()

    edges_disim = [edges_disim, disim_probas]
    edges['disim'] = edges_disim

    for k in edges.keys():
        if (len(edges[k]) == 0):
            edges[k] = torch.tensor([]).to(probas)

    return edges


def get_edges_keypoint_probas(probas, data, edges_nn, thrs=[0.6, 0.8]):

    edges = {'sim': [], 'disim': []}

    max_node = 0
    n_nodes = [g.number_of_nodes() for g in data['graph']]
    for labels, n_nodes_ in zip(data['label_keypoints'], n_nodes):
        for l in labels:
            l += max_node

            # get edges with one node on keypoint
            edges_mask = edges_nn[:, 0] == l
            edges_mask += edges_nn[:, 1] == l

            if (edges_mask.sum() > 0):
                # get edges with nodes with proba > thr
                edges_mask_sim = edges_mask * probas[edges_nn[:, 0]] >= thrs[1]
                edges_mask_sim *= probas[edges_nn[:, 1]] >= thrs[1]
                edges_sim = edges_nn[edges_mask_sim, :]
                edges['sim'].append(edges_sim)

                # get edges with nodes with proba < thr
                edges_mask_disim = edges_mask * probas[edges_nn[:,
                                                                0]] <= thrs[0]
                edges_mask_disim *= probas[edges_nn[:, 1]] <= thrs[0]
                edges_disim = edges_nn[edges_mask_disim, :]
                edges['disim'].append(edges_disim)

        max_node += n_nodes_ + 1

    for k in edges.keys():
        if (len(edges[k]) == 0):
            edges[k] = torch.tensor([]).to(probas)

    return edges


class LabelPairwiseLoss(nn.Module):
    def __init__(self, thrs=[0.6, 0.8]):
        super(LabelPairwiseLoss, self).__init__()
        self.criterion = nn.BCELoss(reduction='none')
        self.thrs = thrs

    def forward(self, edges_nn, probas, feats, clusters=None):

        edges = get_edges_probas(probas,
                                 edges_nn,
                                 thrs=self.thrs,
                                 clusters=clusters)
        constrained_feats = dict()
        probas = dict()

        constrained_feats['sim'] = torch.stack(
            (feats[edges['sim'][0][:, 0]], feats[edges['sim'][0][:, 1]]))
        constrained_feats['disim'] = torch.stack(
            (feats[edges['disim'][0][:, 0]], feats[edges['disim'][0][:, 1]]))

        probas['sim'] = torch.exp(-torch.norm(
            constrained_feats['sim'][0] - constrained_feats['sim'][1], dim=1))
        probas['disim'] = torch.exp(-torch.norm(constrained_feats['disim'][0] -
                                                constrained_feats['disim'][1],
                                                dim=1))

        n_pos = probas['sim'].numel()
        n_neg = probas['disim'].numel()
        pos_weight = float(max((n_pos, n_neg))) / n_pos
        neg_weight = float(max((n_pos, n_neg)) / n_neg)

        weights = torch.cat((torch.ones_like(probas['sim']) * pos_weight,
                             torch.ones_like(probas['disim']) * neg_weight))
        loss = self.criterion(
            torch.cat((probas['sim'], probas['disim'])),
            torch.cat((edges['sim'][1], edges['disim'][1])).float())
        loss *= weights

        return loss.mean()


class LabelKLPairwiseLoss(nn.Module):
    def __init__(self, thr=0.5):
        super(LabelKLPairwiseLoss, self).__init__()
        self.criterion_clst = torch.nn.KLDivLoss(reduction='mean')
        self.criterion_pw = torch.nn.KLDivLoss(reduction='mean')
        self.thr = thr

    def forward(self, edges_nn, probas, clusters, targets, keypoints=None):

        edges = get_edges_probas(probas,
                                 edges_nn,
                                 thrs=[self.thr, self.thr],
                                 clusters=targets)
        # clusters=targets)

        if (keypoints is not None):
            # filter out similar edges
            mask = torch.zeros(edges['sim'][0].shape[0]).to(clusters).bool()
            for kp in keypoints:
                mask += edges['sim'][0][:, 0] == kp
                mask += edges['sim'][0][:, 1] == kp

            edges['sim'][0] = edges['sim'][0][mask, :]

        loss_pw = torch.tensor((0.)).to(clusters)

        clst_sim = torch.stack(
            (clusters[edges['sim'][0][:, 0]], clusters[edges['sim'][0][:, 1]]))
        tgt_sim = torch.stack(
            (targets[edges['sim'][0][:, 0]], targets[edges['sim'][0][:, 1]]))
        clst_disim = torch.stack(
            (clusters[edges['disim'][0][:,
                                        0]], clusters[edges['disim'][0][:,
                                                                        1]]))
        tgt_disim = torch.stack(
            (targets[edges['disim'][0][:, 0]], targets[edges['disim'][0][:,
                                                                         1]]))

        n_pos = edges['sim'][0].shape[0]
        n_neg = edges['disim'][0].shape[0]

        if (n_pos > 0):
            loss_sim = self.criterion_pw(
                (clst_sim[0] + 1e-7).log(), tgt_sim[1]) / clst_sim[0].shape[0]
            loss_sim += self.criterion_pw(
                (clst_sim[1] + 1e-7).log(), tgt_sim[0]) / clst_sim[0].shape[0]
            loss_sim = loss_sim / 2
            pos_weight = float(max((n_pos, n_neg))) / n_pos
            # loss_pw += loss_sim * pos_weight
            loss_pw += loss_sim

        # if (n_neg > 0):
        #     loss_disim = self.criterion_pw(
        #         (clst_disim[0] + 1e-7).log(),
        #         tgt_disim[1]) / clst_disim[0].shape[0]
        #     loss_disim += self.criterion_pw(
        #         (clst_disim[1] + 1e-7).log(),
        #         tgt_disim[0]) / clst_disim[0].shape[0]
        #     neg_weight = float(max((n_pos, n_neg)) / n_neg)
        #     loss_pw -= loss_disim * neg_weight

        return loss_pw


class PairwiseContrastive(nn.Module):
    def __init__(self, margin=0.2):
        super(PairwiseContrastive, self).__init__()
        self.bce = nn.BCELoss(reduction='none')
        self.margin = 0.

    def forward(self, input, target):

        loss = self.bce(input, target)

        loss_pos = loss[target == 1]
        loss_pos = loss_pos[loss_pos <= 1 - self.margin].mean()

        loss_neg = loss[target == 0]
        loss_neg = loss_neg[loss_neg >= self.margin].mean()

        return (loss_neg + loss_pos) / 2


class EmbeddingLoss(nn.Module):
    def __init__(self):
        super(EmbeddingLoss, self).__init__()

    def pos_embedding_loss(self, z, pos_edge_index):
        """Computes the triplet loss between positive node pairs and sampled
        non-node pairs.

        Args:
            z (Tensor): The node embeddings.
            pos_edge_index (LongTensor): The positive edge indices.
        """
        i, j, k = structured_negative_sampling(pos_edge_index, z.size(0))

        out = (z[i] - z[j]).pow(2).sum(dim=1) - (z[i] - z[k]).pow(2).sum(dim=1)
        return torch.clamp(out, min=0).mean()

    def neg_embedding_loss(self, z, neg_edge_index):
        """Computes the triplet loss between negative node pairs and sampled
        non-node pairs.

        Args:
            z (Tensor): The node embeddings.
            neg_edge_index (LongTensor): The negative edge indices.
        """
        i, j, k = structured_negative_sampling(neg_edge_index, z.size(0))

        out = (z[i] - z[k]).pow(2).sum(dim=1) - (z[i] - z[j]).pow(2).sum(dim=1)
        return torch.clamp(out, min=0).mean()

    def forward(self, z, pos_edges, neg_edges):

        loss_1 = self.pos_embedding_loss(z, pos_edges)
        loss_2 = self.neg_embedding_loss(z, neg_edges)
        return loss_1 + loss_2


def structured_negative_sampling(edge_index):
    r"""Samples a negative sample :obj:`(k)` for every positive edge
    :obj:`(i,j)` in the graph given by :attr:`edge_index`, and returns it as a
    tuple of the form :obj:`(i,j,k)`.

    Args:
        edge_index (LongTensor): The edge indices.
        num_nodes (int, optional): The number of nodes, *i.e.*
            :obj:`max_val + 1` of :attr:`edge_index`. (default: :obj:`None`)

    :rtype: (LongTensor, LongTensor, LongTensor)
    """
    num_nodes = edge_index.max().item() + 1

    i, j = edge_index.to('cpu')
    idx_1 = i * num_nodes + j

    k = torch.randint(num_nodes, (i.size(0), ), dtype=torch.long)
    idx_2 = i * num_nodes + k

    mask = torch.from_numpy(np.isin(idx_2, idx_1)).to(torch.bool)
    rest = mask.nonzero().view(-1)
    while rest.numel() > 0:  # pragma: no cover
        tmp = torch.randint(num_nodes, (rest.numel(), ), dtype=torch.long)
        idx_2 = i[rest] * num_nodes + tmp
        mask = torch.from_numpy(np.isin(idx_2, idx_1)).to(torch.bool)
        k[rest] = tmp
        rest = rest[mask.nonzero().view(-1)]

    return edge_index[0], edge_index[1], k.to(edge_index.device)


def complete_graph_from_list(L, create_using=None):
    G = nx.empty_graph(len(L), create_using)
    if len(L) > 1:
        if G.is_directed():
            edges = itertools.permutations(L, 2)
        else:
            edges = itertools.combinations(L, 2)
        G.add_edges_from(edges)
    return G


class CosineSoftMax(nn.Module):
    def __init__(self, kappa=20.):
        super(CosineSoftMax, self).__init__()
        self.kappa = kappa
        self.loss = nn.CrossEntropyLoss(reduction='none')

    def forward(self, z, targets):

        targets_ = targets.argmax(dim=1).to(z.device)

        bc = torch.bincount(targets_)
        freq_weights = bc.max() / bc.float()
        freq_smp_weights = freq_weights[targets.argmax(dim=1)]
        inputs = self.kappa * z

        loss = (freq_smp_weights * self.loss(inputs, targets_)).mean()
        return loss


def make_coord_map(batch_size, w, h):
    xx_ones = torch.ones([1, 1, 1, w], dtype=torch.int32)
    yy_ones = torch.ones([1, 1, 1, h], dtype=torch.int32)

    xx_range = torch.arange(w, dtype=torch.int32)
    yy_range = torch.arange(h, dtype=torch.int32)
    xx_range = xx_range[None, None, :, None]
    yy_range = yy_range[None, None, :, None]

    xx_channel = torch.matmul(xx_range, xx_ones)
    yy_channel = torch.matmul(yy_range, yy_ones)

    # transpose y
    yy_channel = yy_channel.permute(0, 1, 3, 2)

    xx_channel = xx_channel.float() / (w - 1)
    yy_channel = yy_channel.float() / (h - 1)

    xx_channel = xx_channel * 2 - 1
    yy_channel = yy_channel * 2 - 1

    xx_channel = xx_channel.repeat(batch_size, 1, 1, 1)
    yy_channel = yy_channel.repeat(batch_size, 1, 1, 1)

    out = torch.cat([xx_channel, yy_channel], dim=1)

    return out


def sample_triplets(edges):

    # for each clique, generate a mask
    tplts = []
    for c in torch.unique(edges[-1, :]):
        cands = torch.unique(edges[:2, edges[-1, :] != c].flatten())
        idx = torch.randint(0,
                            cands.numel(),
                            size=((edges[-1, :] == c).sum(), ))
        tplts.append(
            torch.cat((edges[:2, edges[-1, :] == c], cands[idx][None, ...]),
                      dim=0))

    tplts = torch.cat(tplts, dim=1)

    return tplts


class PointLoss(nn.Module):
    def __init__(self):
        super(PointLoss, self).__init__()
        self.sigmoid = nn.Sigmoid()

    def forward(self, input, labels, labels_clicked):

        labels_clicked_batch = []
        max_l = 0
        for i, l in enumerate(labels_clicked):
            labels_clicked_batch.append([l_ + max_l for l_ in l])
            max_l += torch.unique(labels[i]).numel() + 1

        idx = torch.tensor(labels_clicked_batch).to(input.device).flatten()
        loss = -(torch.log(self.sigmoid(input[idx]) + 1e-8)).mean()

        return loss


class LSMLoss(nn.Module):
    def __init__(self, K=0.5, T=0.1):
        super(LSMLoss, self).__init__()
        self.cs = nn.CosineSimilarity(dim=1)
        self.K = K
        self.T = T

    def forward(self, feats, edges):
        """
        Computes the triplet loss between positive node pairs and sampled
        non-node pairs.
        """

        # remove negative edges
        edges = edges[:, edges[-1, :] != -1]
        tplts = sample_triplets(edges)

        cs_ap = self.cs(feats[tplts[0]], feats[tplts[1]])
        cs_an = self.cs(feats[tplts[0]], feats[tplts[2]])

        loss_ap = torch.log1p(torch.exp(-(cs_ap - self.K) / self.T))
        loss_an = torch.log1p(torch.exp((cs_an - self.K) / self.T))

        return loss


def num_nan_inf(t):
    return torch.isnan(t).sum() + torch.isinf(t).sum()


def do_previews(images, labels, pos_nodes, neg_nodes):
    import matplotlib.pyplot as plt

    max_node = 0
    ims = []
    for im in images:
        im = (255 *
              np.rollaxis(im.squeeze().detach().cpu().numpy(), 0, 3)).astype(
                  np.uint8)
        ims.append(im)

    labels = labels.squeeze().detach().cpu().numpy()
    pos_map = np.zeros_like(labels)
    neg_map = np.zeros_like(labels)

    for n in pos_nodes:
        pos_map[labels == n.item()] = True
    for n in neg_nodes:
        neg_map[labels == n.item()] = True

    pos_map = np.concatenate([a for a in pos_map], axis=0)
    neg_map = np.concatenate([a for a in neg_map], axis=0)
    maps = np.concatenate((pos_map, neg_map), axis=1)
    ims = np.concatenate(ims, axis=0)

    cmap = plt.get_cmap('viridis')
    maps = (cmap(
        (maps * 255).astype(np.uint8))[..., :3] * 255).astype(np.uint8)

    all_ = np.concatenate((ims, maps), axis=1)

    return all_


def get_pos_negs(keypoints, nodes, input, mode='all'):
    # edges_ = edges[:, edges[-1] != -1]

    # print('keypoints: {}'.format(keypoints))
    # print('frames: {}'.format(data['frame_idx']))
    # print('sum(edges_[0] == k): {}'.format(
    #     torch.cat([edges_[0] == l for l in keypoints]).sum()))
    # print('sum(edges_[1] == k): {}'.format(
    #     torch.cat([edges_[0] == l for l in keypoints]).sum()))
    # get edges that corresponds to keypoints
    #
    assert mode in ['all', 'rand_weighted',
                    'rand_uniform'], print('mode should be either all or rand')
    all_clusters = torch.unique(nodes[-1])

    if (len(keypoints) > 0):
        cluster_clicked = torch.cat(
            [nodes[-1, (nodes[0, :] == l)] for l in keypoints])

        pos_nodes = torch.cat([
            torch.unique(nodes[0, nodes[-1] == c])
            for c in torch.unique(cluster_clicked)
        ])

        if ('rand' in mode):
            compareview = cluster_clicked.repeat(all_clusters.shape[0], 1).T
            neg_clusters = all_clusters[(
                compareview != all_clusters).T.prod(1) == 1]

            neg_nodes = [
                torch.unique(nodes[0, nodes[-1] == c]) for c in neg_clusters
            ]
            if ('weighted' in mode):
                weights = torch.tensor([len(n) for n in neg_nodes
                                        ]).to(all_clusters.device)
                weights = weights.max().float() / weights.float()
            else:
                weights = torch.ones(len(neg_nodes)).to(all_clusters.device)

            neg_cluster_idx = torch.multinomial(weights, 1, replacement=True)
            neg_cluster = neg_clusters[neg_cluster_idx]
            neg_nodes = torch.unique(nodes[:2, nodes[-1] == neg_cluster])
        else:
            neg_nodes = random.choice(neg_nodes)

        pos_tgt = torch.ones(pos_nodes.numel()).float().to(nodes.device)
        neg_tgt = torch.zeros(neg_nodes.numel()).float().to(nodes.device)
        tgt = torch.cat((neg_tgt, pos_tgt))
        input = torch.cat((input[neg_nodes], input[pos_nodes]))
    else:
        tgt = torch.zeros(input.numel()).to(nodes.device)

    # path = '/home/ubelix/artorg/lejeune/runs/maps_{:04d}.png'.format(
    #     data['frame_idx'][0])
    # if (not os.path.exists(path)):
    #     maps = do_previews(data['image'], data['labels'], pos_nodes,
    #                        neg_nodes)
    #     io.imsave(path, maps)

    return input, tgt


class ClusterDiceLoss(nn.Module):
    def __init__(self, smooth=1., square=False):
        super(ClusterDiceLoss, self).__init__()
        self.loss = SoftDiceLoss(smooth=smooth, square=square)

    def forward(self, input, edges, data):
        """
        """

        input, tgt = get_pos_negs(data['clicked'], edges, input)
        input = input[None, None, ..., None]
        tgt = tgt[None, None, ..., None]

        return self.loss(input.sigmoid(), tgt)


class ClusterFocalLoss(nn.Module):
    def __init__(self, gamma=0.5, alpha=0.25, mode='all'):
        super(ClusterFocalLoss, self).__init__()
        self.gamma = gamma
        self.alpha = alpha
        self.eps = 1e-6
        self.mode = mode

    def forward(self, input, nodes, data, override_alpha=None):
        """
        """

        if (override_alpha is None):
            alpha = self.alpha
        else:
            alpha = override_alpha

        input, tgt = get_pos_negs(data['clicked'], nodes, input, self.mode)

        logit = input.sigmoid().clamp(self.eps, 1 - self.eps)
        pt0 = 1 - logit[tgt == 0]
        pt1 = logit[tgt == 1]
        loss = F.binary_cross_entropy_with_logits(input, tgt, reduction='none')
        loss[tgt == 1] = loss[tgt == 1] * alpha * (1 - pt1)**self.gamma
        loss[tgt == 0] = loss[tgt == 0] * (1 - alpha) * (1 - pt0)**self.gamma

        return loss.mean()


class RAGTripletLoss(nn.Module):
    def __init__(self):
        super(RAGTripletLoss, self).__init__()
        self.cs = nn.CosineSimilarity(dim=1)
        # self.cs = nn.CosineSimilarity(dim=1, eps=1e-3)
        self.margin = 0.5

    def forward(self, feats, edges):
        """
        Computes the triplet loss between positive node pairs and sampled
        non-node pairs.
        """

        # remove negative edges
        edges = edges[:, edges[-1, :] != -1]
        tplts = sample_triplets(edges)

        xa = feats[tplts[0]]
        xp = feats[tplts[1]]
        xn = feats[tplts[2]]
        # print('[RAGTripletLoss] num. NaN feats: {}'.format(
        #     num_nan_inf(xa) + num_nan_inf(xp) + num_nan_inf(xn)))
        cs_ap = self.cs(xa, xp)
        cs_an = self.cs(xa, xn)
        # print('[RAGTripletLoss] num. NaN cs: {}'.format(
        #     num_nan_inf(cs_ap) + num_nan_inf(cs_an)))
        dap = 1 - cs_ap
        dan = 1 - cs_an

        # weight by clique size
        # bc = torch.bincount(edges[-1])
        # freq_weights = bc.float() / edges.shape[-1]
        # freq_smp_weights = freq_weights[edges[-1]]

        # loss = torch.log1p(dap - dan)
        loss = torch.clamp(dap - dan + self.margin, min=0)
        loss = loss[loss > 0]
        loss = loss.mean()
        # print('[RAGTripletLoss] loss: {}'.format(loss))

        return loss


def cosine_distance_torch(x1, x2=None, eps=1e-8):
    x2 = x1 if x2 is None else x2
    w1 = x1.norm(p=2, dim=1, keepdim=True)
    w2 = w1 if x2 is x1 else x2.norm(p=2, dim=1, keepdim=True)
    return 1 - torch.mm(x1, x2.t()) / (w1 * w2.t()).clamp(min=eps)


class BatchHardTripletSelector(object):
    '''
    a selector to generate hard batch embeddings from the embedded batch
    '''
    def __init__(self, *args, **kwargs):
        super(BatchHardTripletSelector, self).__init__()

    def __call__(self, embeds, labels):
        dist_mtx = cosine_distance_torch(embeds, embeds).detach().cpu().numpy()
        labels = labels.contiguous().cpu().numpy().reshape((-1, 1))
        num = labels.shape[0]
        dia_inds = np.diag_indices(num)
        lb_eqs = labels == labels.T
        lb_eqs[dia_inds] = False
        dist_same = dist_mtx.copy()
        dist_same[lb_eqs == False] = -np.inf
        pos_idxs = np.argmax(dist_same, axis=1)
        dist_diff = dist_mtx.copy()
        lb_eqs[dia_inds] = True
        dist_diff[lb_eqs == True] = np.inf
        neg_idxs = np.argmin(dist_diff, axis=1)
        pos = embeds[pos_idxs].contiguous().view(num, -1)
        neg = embeds[neg_idxs].contiguous().view(num, -1)
        return embeds, pos, neg


class TripletLoss(nn.Module):
    def __init__(self, margin=0.7):
        super(TripletLoss, self).__init__()
        self.margin = margin

    def forward(self, sim_ap, sim_an, dr_an=None):
        """Computes the triplet loss between positive node pairs and sampled
        non-node pairs.
        """

        dap = 1 - sim_ap
        dan = 1 - sim_an

        loss = torch.clamp(dap - dan + self.margin, min=0)
        loss = loss[loss > 0]
        loss = loss.mean()

        return loss


if __name__ == "__main__":
    N = 1000
    eps = 1e-8
    alpha = 0.9
    gamma = 0.2
    input = torch.randn(N)
    tgt = torch.randint(0, 2, size=(N, ))

    logit = input.sigmoid()
    logit = logit.clamp(eps, 1. - eps)
    pt0 = logit[tgt == 0]
    pt1 = 1 - logit[tgt == 1]
    loss0 = -alpha * (1 - pt1)**gamma * torch.log(pt1)
    loss0 = loss0.mean()
    loss1 = -(1 - alpha) * (1 - pt0)**gamma * torch.log(pt0)
    loss1 = loss1.mean()
    loss = loss0 + loss1

    print(loss.mean())

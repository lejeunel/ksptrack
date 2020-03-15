from torch import nn
import numpy as np
import torch
from torch.nn import functional as F


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
                edges_mask_disim = edges_mask * probas[
                    edges_nn[:, 0]] <= thrs[0]
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

        edges = get_edges_probas(probas, edges_nn, thrs=[self.thr, self.thr],
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
        clst_disim = torch.stack((clusters[edges['disim'][0][:, 0]],
                                  clusters[edges['disim'][0][:, 1]]))
        tgt_disim = torch.stack((targets[edges['disim'][0][:, 0]],
                                 targets[edges['disim'][0][:, 1]]))

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


class LDALoss(nn.Module):
    def __init__(self, thr=0.5):
        super(LDALoss, self).__init__()
        self.n_classes = 2
        self.thr = thr
        self.lamb = 1e-2
        self.margin = 2
        self.n_comps = 4

    def forward(self, H, probas):
        N, C = H.shape

        H_bar = H - torch.mean(H, 0, True)
        labels = (probas >= self.thr).int()

        S_w = torch.Tensor().new_zeros((C, C)).float().to(H)
        S_t = H_bar.t().matmul(H_bar) / (N - 1)
        for i in range(self.n_classes):
            H_i = H[labels == i]
            H_i_bar = H_i - torch.mean(H_i, 0, True)
            N_i = H_i.shape[0]
            if N_i == 0:
                continue
            S_w += H_i_bar.t().matmul(H_i_bar) / (N_i - 1) / self.n_classes
        temp = (S_w + self.lamb * torch.eye(C).to(H)).float().pinverse().matmul(S_t - S_w)
        eig_vals, eig_vecs = torch.symeig(temp, eigenvectors=True)
        eig_vals = eig_vals.detach()
        eig_vecs = eig_vecs.detach()

        thresh = eig_vals.min() + self.margin
        eig_vals = eig_vals[(eig_vals <= thresh).nonzero()]
        loss = eig_vals.mean()
        return loss


if __name__ == "__main__":
    from ksptrack.models.my_augmenters import Normalize
    from torch.utils.data import DataLoader
    from ksptrack.siamese.modeling.siamese import Siamese
    from ksptrack.utils.bagging import calc_bagging
    from loader import Loader
    from os.path import join as pjoin
    import clustering as clst
    from ksptrack.siamese import utils as utls

    device = torch.device('cuda')
    transf_normal = Normalize(mean=[0.485, 0.456, 0.406],
                              std=[0.229, 0.224, 0.225])

    dl = Loader(pjoin('/home/ubelix/artorg/lejeune/data/medical-labeling',
                      'Dataset00'),
                normalization=transf_normal)
    dl_train = DataLoader(dl, collate_fn=dl.collate_fn, batch_size=2, shuffle=True)
    dl_prev = DataLoader(dl, collate_fn=dl.collate_fn)

    model = Siamese(10, 10, roi_size=1, roi_scale=1, alpha=1)

    run_path = '/home/ubelix/artorg/lejeune/runs/siamese_dec/Dataset00'
    cp_path = pjoin(run_path, 'checkpoints', 'init_dec.pth.tar')
    state_dict = torch.load(cp_path, map_location=lambda storage, loc: storage)
    model.load_state_dict(state_dict)
    model.to(device)
    model.train()
    criterion = LDALoss()

    features, pos_masks, _ = clst.get_features(model, dl_prev, device)
    cat_features = np.concatenate(features)
    cat_pos_mask = np.concatenate(pos_masks)
    print('computing probability map')
    probas = calc_bagging(cat_features,
                          cat_pos_mask,
                          30,
                          bag_max_depth=64,
                          bag_n_feats=None,
                          bag_max_samples=500,
                          n_jobs=1)
    probas = torch.from_numpy(probas).to(device)
    n_labels = [np.unique(s['labels']).size for s in dl_prev.dataset]
    probas = torch.split(probas, n_labels)

    for data in dl_train:
        # edges_nn, _, _ = make_couple_graphs(model, device, data, 0.1, L, True)
        data = utls.batch_to_device(data, device)
        res = model(data)
        probas_ = torch.cat([probas[i] for i in data['frame_idx']])

        loss = criterion(res['proj_pooled_aspp_feats'], probas_)

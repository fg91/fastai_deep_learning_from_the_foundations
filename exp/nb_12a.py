
#################################################
### THIS FILE WAS AUTOGENERATED! DO NOT EDIT! ###
#################################################
# file to edit: dev_nb/12a_awd_lstm.ipynb

from exp.nb_12 import *

def dropout_mask(x, sz, p):
    return x.new(*sz).bernoulli_(1-p).div_(1-p)

class RNNDropout(nn.Module):
    def __init__(self, p=0.5):
        super().__init__()
        self.p = p

    def forward(self, x):
        if not self.training or self.p == 0.: return x
        m = dropout_mask(x.data, (x.size(0), 1, x.size(2)), self.p)

        return x * m

import warnings

WEIGHT_HH = 'weight_hh_l0'

class WeightDropout(nn.Module):
    def __init__(self, module, weight_p=[0.], layer_names=[WEIGHT_HH]):
        super().__init__()
        self.module,self.weight_p,self.layer_names = module,weight_p,layer_names
        for layer in self.layer_names:
            #Makes a copy of the weights of the selected layers.
            w = getattr(self.module, layer)
            self.register_parameter(f'{layer}_raw', nn.Parameter(w.data))
            self.module._parameters[layer] = F.dropout(w, p=self.weight_p, training=False)

    def _setweights(self):
        for layer in self.layer_names:
            raw_w = getattr(self, f'{layer}_raw')
            self.module._parameters[layer] = F.dropout(raw_w, p=self.weight_p, training=self.training)

    def forward(self, *args):
        self._setweights()
        with warnings.catch_warnings():
            #To avoid the warning that comes because the weights aren't flattened.
            warnings.simplefilter("ignore")
            return self.module.forward(*args)

def to_detach(h):
    "Detaches h from its history."
    return h.detach() if type(h) == torch.Tensor else tuple(to_detach(v) for v in h)

class LinearDecoder(nn.Module):
    def __init__(self, n_out, n_hid, output_p, tie_encoder=None, bias=True):
        super().__init__()
        self.output_dp = RNNDropout(output_p)
        self.decoder = nn.Linear(n_hid, n_out, bias=bias)
        if bias: self.decoder.bias.data.zero_()
        if tie_encoder: self.decoder.weight = tie_encoder.weight
        else: init.kaiming_uniform_(self.decoder.weight)

    def forward(self, input):
        raw_outputs, outputs = input
        # raw_outputs[-1] is equal to outputs[-1]
        output = self.output_dp(outputs[-1]).contiguous()
        decoded = self.decoder(output.view(output.size(0) * output.size(1), output.size(2)))  # (64 * 70, 300) -> (64 * 70, voc_size)
        return decoded, raw_outputs, outputs

class SequentialRNN(nn.Sequential):
    "A sequential module that passes the reset call to its children."
    def reset(self):
        for c in self.children():
            if hasattr(c, 'reset'): c.reset()

class GradientClipping(Callback):
    def __init__(self, clip=None): self.clip = clip
    def after_backward(self):
        if self.clip:
            nn.utils.clip_grad_norm_(self.run.model.parameters(), self.clip)

class RNNTrainer(Callback):
    def __init__(self, alpha, beta):
        self.alpha = alpha
        self.beta  = beta

    def after_pred(self):
        """Return true prediction, save encoder outputs"""
        self.raw_out, self.out = self.pred[1], self.pred[2]
        self.run.pred = self.pred[0]

    def after_loss(self):
        # AR and TAR
        if self.alpha != 0:
            self.run.loss += self.alpha * self.out[-1].float().pow(2).mean()
            # out[-1] has shape [64, 70, 300]
        if self.beta != 0:
            h = self.raw_out[-1]
            if len(h) > 1:  # should this rather be h.size(1) and not bs?
                self.run.loss += self.beta * (h[:,1:] - h[:,:-1]).float().pow(2).mean()

    def begin_epoch(self):
        # Shuffle the texts at the beginning of the epoch
        if hasattr(self.dl.dataset, "batchify"): self.dl.dataset.batchify()

def cross_entropy_flat(input, target):
    bs, sl = target.size()
    return F.cross_entropy(input.view(bs * sl, -1), target.view(bs * sl))

def accuracy_flat(input, target):
    bs, sl = target.size()
    return accuracy(input.view(bs * sl, -1), target.view(bs * sl))
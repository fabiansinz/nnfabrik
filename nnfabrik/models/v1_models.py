from mlutils.layers.readouts import PointPooled2d
from mlutils.layers.cores import Stacked2dCore
from torch import nn as nn
from ..utility.nn_helpers import get_io_dims, get_module_output, set_random_seed, get_dims_for_loader_dict
from torch.nn import functional as F
import numpy as np
from .pretrained_models import TransferLearningCore

class PointPooled2dReadout(nn.ModuleDict):
    def __init__(self, core, in_shape_dict, n_neurons_dict, pool_steps, pool_kern, bias, init_range, gamma_readout):
        # super init to get the _module attribute
        super(PointPooled2dReadout, self).__init__()
        for k in n_neurons_dict:
            in_shape = get_module_output(core, in_shape_dict[k])[1:]
            n_neurons = n_neurons_dict[k]
            self.add_module(k, PointPooled2d(
                            in_shape,
                            n_neurons,
                            pool_steps=pool_steps,
                            pool_kern=pool_kern,
                            bias=bias,
                            init_range=init_range)
                            )

        self.gamma_readout = gamma_readout

    def forward(self, *args, data_key=None, **kwargs):
        if data_key is None and len(self) == 1:
            data_key = list(self.keys())[0]
        return self[data_key](*args, **kwargs)


    def regularizer(self, data_key):
        return self[data_key].feature_l1() * self.gamma_readout


def stacked2d_core_point_readout(dataloaders, seed, hidden_channels=32, input_kern=13,
                                 hidden_kern=3, layers=3, gamma_hidden=0, gamma_input=0.1,
                                 skip=0, final_nonlinearity=True, core_bias=False, momentum=0.9,
                                 pad_input=False, batch_norm=True, hidden_dilation=1,
                                 pool_steps=2, pool_kern=7, readout_bias=True, init_range=0.1,
                                 gamma_readout=0.1, laplace_padding=None):

    session_shape_dict = get_dims_for_loader_dict(dataloaders)

    n_neurons_dict = {k: v['targets'][1] for k, v in session_shape_dict.items()}
    in_shapes_dict = {k: v['inputs'] for k, v in session_shape_dict.items()}
    input_channels = [v['inputs'][1] for _, v in session_shape_dict.items()]
    assert np.unique(input_channels).size == 1, "all input channels must be of equal size"

    class Encoder(nn.Module):

        def __init__(self, core, readout):
            super().__init__()
            self.core = core
            self.readout = readout

        def forward(self, x, data_key=None, **kwargs):
            x = self.core(x)
            x = self.readout(x, data_key=data_key)
            return F.elu(x) + 1

        def regularizer(self, data_key):
            return self.core.regularizer() + self.readout.regularizer(data_key=data_key)

    set_random_seed(seed)

    # get a stacked2D core from mlutils
    core = Stacked2dCore(input_channels=input_channels[0],
                         hidden_channels=hidden_channels,
                         input_kern=input_kern,
                         hidden_kern=hidden_kern,
                         layers=layers,
                         gamma_hidden=gamma_hidden,
                         gamma_input=gamma_input,
                         skip=skip,
                         final_nonlinearity=final_nonlinearity,
                         bias=core_bias,
                         momentum=momentum,
                         pad_input=pad_input,
                         batch_norm=batch_norm,
                         hidden_dilation=hidden_dilation,
                         laplace_padding=laplace_padding)

    readout = PointPooled2dReadout(core, in_shape_dict=in_shapes_dict,
                                   n_neurons_dict=n_neurons_dict,
                                   pool_steps=pool_steps,
                                   pool_kern=pool_kern,
                                   bias=readout_bias,
                                   init_range=init_range,
                                   gamma_readout=gamma_readout)

    # initializing readout bias to mean response
    for k in dataloaders:
        readout[k].bias.data = dataloaders[k].dataset[:][1].mean(0)


    model = Encoder(core, readout)
    return model


def vgg_core_point_readout(dataloaders, seed, pool_steps=1,
                           pool_kern=7, readout_bias=True, init_range=0.1,
                           gamma_readout=0.002):

    session_shape_dict = get_dims_for_loader_dict(dataloaders)

    n_neurons_dict = {k: v['targets'][1] for k, v in session_shape_dict.items()}
    in_shapes_dict = {k: v['inputs'] for k, v in session_shape_dict.items()}
    input_channels = [v['inputs'][1] for _, v in session_shape_dict.items()]
    assert np.unique(input_channels).size == 1, "all input channels must be of equal size"

    class Encoder(nn.Module):

        def __init__(self, core, readout):
            super().__init__()
            self.core = core
            self.readout = readout

        def forward(self, x, data_key=None, **kwargs):
            x = self.core(x)
            x = self.readout(x, data_key=data_key)
            return F.elu(x-1) + 1

        # core regularizer is omitted because it's pretrained
        def regularizer(self, data_key):
            return self.readout.regularizer(data_key=data_key)

    set_random_seed(seed)

    core = TransferLearningCore(input_channels=1, tr_model_fn='vgg16',
                                model_layer=11, momentum=0.1, final_batchnorm=True,
                                final_nonlinearity=True, bias=False)

    readout = PointPooled2dReadout(core, in_shape_dict=in_shapes_dict,
                                   n_neurons_dict=n_neurons_dict,
                                   pool_steps=pool_steps,
                                   pool_kern=pool_kern,
                                   bias=readout_bias,
                                   init_range=init_range,
                                   gamma_readout=gamma_readout)

    # initializing readout bias to mean response
    for k in dataloaders:
        readout[k].bias.data = dataloaders[k].dataset[:][1].mean(0)

    model = Encoder(core, readout)
    return model
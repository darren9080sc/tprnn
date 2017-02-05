# TODO: dropout layers

from __future__ import print_function

import numpy as np
import theano
from theano import config
import theano.tensor as tensor
# from theano.sandbox.rng_mrg import MRG_RandomStreams as RandomStreams
import pdb

# Set the random number generators' seeds for consistency
SEED = 123
np.random.seed(SEED)


def numpy_floatX(data):
    return np.asarray(data, dtype=config.floatX)


def lstm_layer(tparams, state_below, options, seq_masks=None, topo_masks=None):
    '''
    state_below has shape: n_timesteps * n_samples * dim_proj
    topo_masks has shape: n_timesteps * n_samples * n_timesteps
    Returns:
        hidden states for each step, shape = n_timesteps * n_samples *dim_proj
    '''
    n_timesteps = state_below.shape[0]
    if state_below.ndim == 3:
        n_samples = state_below.shape[1]
    else:
        n_samples = 1

    assert seq_masks is not None
    assert topo_masks is not None

    def _slice(_x, n, dim):
        if _x.ndim == 3:
            return _x[:, :, n * dim:(n + 1) * dim]
        return _x[:, n * dim:(n + 1) * dim]

    def _step(index, seq_m_, topo_m_, x_, h_arr_, c_arr_):
        '''
        topo_m_: shape = n_samples * n_timesteps
        h_arr_: shape = n_timesteps * n_samples * dim_proj
        '''
        # tranposes h_arr_ to have shape n_samples * n_timesteps * dim_proj
        # h_sum_ has shape n_samples * dim_proj
        h_sum = (topo_m_[:, :, None] * h_arr_.dimshuffle(1, 0, 2)).sum(axis=1)
        c_sum = (topo_m_[:, :, None] * c_arr_.dimshuffle(1, 0, 2)).sum(axis=1)

        # lstm_U has shape dim_proj * (4*dim_proj)
        preact = tensor.dot(h_sum, tparams['lstm_U'])
        preact += x_

        # here simply use same forget gate for all predecesors
        i = tensor.nnet.sigmoid(_slice(preact, 0, options['dim_proj']))
        f = tensor.nnet.sigmoid(_slice(preact, 1, options['dim_proj']))
        o = tensor.nnet.sigmoid(_slice(preact, 2, options['dim_proj']))
        c = tensor.tanh(_slice(preact, 3, options['dim_proj']))

        c = f * c_sum + i * c
        c = seq_m_[:, None] * c

        h = o * tensor.tanh(c)
        h = seq_m_[:, None] * h

        h_arr_ = tensor.set_subtensor(h_arr_[index, :], h)
        c_arr_ = tensor.set_subtensor(c_arr_[index, :], c)

        return h_arr_, c_arr_

    state_below = (tensor.dot(state_below, tparams['lstm_W']) +
                   tparams['lstm_b'])

    dim_proj = options['dim_proj']
    rval, updates = theano.scan(_step,
                                sequences=[tensor.arange(n_timesteps),
                                           seq_masks,
                                           topo_masks,
                                           state_below],
                                outputs_info=[tensor.alloc(numpy_floatX(0.),
                                                           n_timesteps, n_samples, dim_proj),
                                              tensor.alloc(numpy_floatX(0.),
                                                           n_timesteps, n_samples, dim_proj)],
                                name='lstm_layers',
                                n_steps=n_timesteps)

    return rval[0][-1]


def build_model(tparams, options):
    # set up input symbols
    seqs = tensor.matrix('seqs', dtype='int32')
    seq_masks = tensor.matrix('seq_masks', dtype=config.floatX)
    topo_masks = tensor.tensor3('topo_masks', dtype=config.floatX)
    target_masks = tensor.matrix('target_masks', dtype=config.floatX)
    labels = tensor.vector('labels', dtype='int32')

    input_list = [seqs, seq_masks, topo_masks, target_masks]

    n_timesteps = seqs.shape[0]
    n_samples = seqs.shape[1]

    # embedding lookup.
    embs = tparams['Wemb'][seqs.flatten()].reshape([n_timesteps,
                                                    n_samples,
                                                    options['dim_proj']])

    # run through lstm layer.
    # h_arr.shape = (n_timesteps, n_samples, dim_proj)
    h_arr = lstm_layer(tparams, embs, options, seq_masks=seq_masks, topo_masks=topo_masks)

    # customized softmax using masks
    logits = tensor.dot(h_arr.dimshuffle(1, 0, 2), tparams['theta'])
    exps = tensor.exp(logits) * target_masks
    probs = exps / (exps.sum(axis=1))[:, None]

    # set up cost
    off = 1e-8
    cost = -tensor.log(probs[tensor.arange(n_samples), labels] + off).mean()

    # l2 penalty terms
    cost += options['decay_lstm_W'] * (tparams['lstm_W'] ** 2).sum()
    cost += options['decay_lstm_U'] * (tparams['lstm_U'] ** 2).sum()
    cost += options['decay_lstm_b'] * (tparams['lstm_b'] ** 2).sum()
    cost += options['decay_theta'] * (tparams['theta'] ** 2).sum()

    # set up functions for inferencing
    f_prob = theano.function(input_list, probs, name='f_prob')
    f_pred = theano.function(input_list, probs.argmax(axis=1), name='f_pred')

    return input_list, labels, cost, f_prob, f_pred
# TODO: dropout layers

from __future__ import print_function

import numpy as np
import theano
from theano import config
import theano.tensor as tensor


# Set the random number generators' seeds for consistency
# SEED = 123
# np.random.seed(SEED)


def numpy_floatX(data):
    return np.asarray(data, dtype=config.floatX)


def lstm_layer(tparams, state_below, options, seq_masks=None, topo_masks=None):
    '''
    The LSTM model.
    state_below.shape (n_timesteps, n_samples, dim_proj)
    topo_masks.shape: (n_timesteps, n_samples, n_timesteps)

    Returns:
        a tensor of hidden states for all steps, has shape (n_timesteps, n_samples, dim_proj).
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
        A LSTM step.
        topo_m_.shape = (n_samples, n_timesteps)
        h_arr_.shape shape = (n_timesteps, n_samples, dim_proj)
        '''
        # tranposes h_arr_ to have shape (n_samples, n_timesteps, dim_proj)
        # h_sum_ has shape n_samples * dim_proj
        h_sum = (topo_m_[:, :, None] * h_arr_.dimshuffle(1, 0, 2)).sum(axis=1)
        c_sum = (topo_m_[:, :, None] * c_arr_.dimshuffle(1, 0, 2)).sum(axis=1)

        # lstm_U.shape = (dim_proj, 4*dim_proj)
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
    '''
    Builds Topo-LSTM model.
    Returns a dictionary of outlet symbols
    '''
    # Set up input symbols with shapes:
    #   seqs.shape = (n_timesteps, n_samples)
    #   seq_masks.shape = (n_timesteps, n_samples)
    #   topo_masks.shape = (n_timesteps, n_samples, n_timesteps)
    #   labels.shape = (n_samples,)
    seqs = tensor.matrix('seqs', dtype='int32')
    seq_masks = tensor.matrix('seq_masks', dtype=config.floatX)
    topo_masks = tensor.tensor3('topo_masks', dtype=config.floatX)

    input_list = [seqs, seq_masks, topo_masks]
    labels = tensor.vector('labels', dtype='int32')

    n_timesteps = seqs.shape[0]
    n_samples = seqs.shape[1]

    # embedding lookup.
    embs = tparams['Wemb'][seqs.flatten()].reshape([n_timesteps,
                                                    n_samples,
                                                    options['dim_proj']])

    # run through lstm layer.
    # h_arr.shape = (n_timesteps, n_samples, dim_proj)
    h_arr = lstm_layer(tparams, embs, options, seq_masks=seq_masks, topo_masks=topo_masks)

    # mean pooling of hidden states, h_mean.shape=(n_samples, dim_proj)
    h_sum = (seq_masks[:, :, None] * h_arr).sum(axis=0)
    lengths = seq_masks.sum(axis=0)
    h_mean = h_sum / lengths[:, None]

    # decoding, probs.shape=(n_samples, n_words)
    logits = tensor.dot(h_mean, tparams['dec_W']) + tparams['dec_b'][None, :]
    probs = tensor.nnet.softmax(logits)

    # set up cost
    cost = tensor.nnet.nnet.categorical_crossentropy(probs, labels).mean()
    f_eval = theano.function(input_list + [labels], cost, name='f_eval')

    # L2 penalty terms
    cost += options['weight_decay'] * (tparams['lstm_W'] ** 2).sum()
    cost += options['weight_decay'] * (tparams['lstm_U'] ** 2).sum()
    cost += options['weight_decay'] * (tparams['lstm_b'] ** 2).sum()
    cost += options['weight_decay'] * (tparams['dec_W'] ** 2).sum()
    cost += options['weight_decay'] * (tparams['dec_b'] ** 2).sum()

    # set up functions for inferencing
    f_prob = theano.function(input_list, probs, name='f_prob')
    f_pred = theano.function(input_list, probs.argmax(axis=1), name='f_pred')

    return {'inputs': input_list,
            'labels': labels,
            'cost': cost,
            'f_prob': f_prob,
            'f_pred': f_pred,
            'f_eval': f_eval,
            'data': input_list + [labels]}

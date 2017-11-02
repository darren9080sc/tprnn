import networkx as nx
import random
import numpy as np
import os
import pprint

import data_utils
import metrics


data_dir = 'data/digg'
maxlen = 30
method = 'ic'

random.seed(0)


def ic_pred_probs(sequence, G=None):
    '''
    IC: independent cascade.
    Assuming G's nodes have indexes in [0, N-1].
    '''
    N = len(G.nodes())
    prob_comp = np.ones(N)
    result = []

    for i, src in enumerate(sequence):
        for target, atrbs in G[src].iteritems():
            edge_prob = atrbs['weight']
            prob_comp[target] *= (1 - edge_prob)

        prob = 1. - prob_comp
        prob[sequence[:i + 1]] = 0.
        if np.sum(prob) < 1e-8:
            prob = np.ones(N)
        prob /= float(np.sum(prob))
        result += [prob]

    return result


def lt_pred_probs(sequence, G=None, tol=0.0001):
    """
    LT: linear threshold.
    """
    N = len(G.nodes())
    acc = np.zeros(N)
    thresholds = np.ones(N) * 1e8
    result = []

    for src in sequence:
        for target, atrbs in G[src].iteritems():
            edge_prob = atrbs['weight']
            if thresholds[target] > 1.:
                thresholds[target] = random.random() * 0.
            acc[target] += edge_prob

        prob = acc
        prob[thresholds > 1.] = 0.
        prob[prob < thresholds + tol] = 0.
        # prob[prob > 0] = 1.
        prob /= np.sum(prob) + 1e-8

        result += [prob]

    return result


def evaluate(G=None, k_list=[10, 50, 100]):
    y_prob = []
    y = []
    input_test_file = os.path.join(data_dir, 'test.txt')
    with open(input_test_file, 'rb') as f:
        for line in f:
            _, cascade = line.strip().split(' ', 1)
            sequence = cascade.split()[::2][:maxlen]
            sequence = [node_index[x] for x in sequence]
            y_prob_ = ic_pred_probs(sequence[:-1], G=G)
            y_ = sequence[1:]
            y_prob += y_prob_
            y += y_

    return metrics.portfolio(y_prob, y, k_list=k_list)


_, node_index = data_utils.load_graph(data_dir)

# loads probability graph (cascade subgraph with original ids).
temp_graph = nx.DiGraph()
temp_graph.add_nodes_from(node_index.keys())
input_graph_file = os.path.join(data_dir, 'prob_graph.txt')
with open(input_graph_file, 'rb') as f:
    for line in f:
        u, v, p = line.strip().split()
        p = float(p)
        temp_graph.add_edge(u, v, weight=p)

G = nx.relabel_nodes(temp_graph, node_index)
print nx.info(G)

pprint.pprint(evaluate(G=G))
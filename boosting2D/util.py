import sys
import config
import time
from datetime import datetime
import pickle
import copy
import gzip
import pdb

import numpy as np 
import sklearn.utils
from scipy.sparse import *
import random

from boosting2D import config


### Log 
##########################################

class Logger():
    def __init__(self, ofp=sys.stderr, verbose=config.VERBOSE):
        self.ofp = ofp
        self.verbose = verbose
    
    def __call__(self, msg, log_time=True, level='QUIET'):
        if config.VERBOSE == False:
            if level is not 'VERBOSE': return
        if log_time:
            time_stamp = datetime.fromtimestamp(time.time()).strftime(
                '%Y-%m-%d %H:%M:%S: ')
            msg = time_stamp + msg
        self.ofp.write(msg.strip() + "\n")

def get_metric_from_tree(tree, metric, index, split='train'):
    METRIC_DICT = {
        'imbalanced_error,train': 'imbal_train_err',
        'imbalanced_error,test': 'imbal_test_err',
        'balanced_error,train': 'bal_train_err',
        'balanced_error,test': 'bal_test_err',
        'auPRC,train': 'train_auprc',
        'auPRC,test': 'test_auprc',
        'auROC,train': 'train_auroc',
        'auROC,test': 'test_auroc',
    }
    metric_name = METRIC_DICT['%s,%s'%(metric, split)]
    out_str = '{0} - {1}: {2}'.format(metric, split, getattr(tree, metric_name)[index])
    return out_str

def log_progress(tree, i, x1, x2, hierarchy, ofp=None, verbose=True):
    msg_contents = ['iteration: {0}'.format(i)]
    x1_split = ','.join([x1.row_labels[el] for el in
                         np.unique([tree.split_x1[i]] + tree.bundle_x1[i]).tolist()])
    x2_split = ','.join([x2.col_labels[el] for el in 
                         np.unique([tree.split_x2[i]] + tree.bundle_x2[i]).tolist()])
    rule_message = ['x1 split feat: {0}'.format(x1_split),
                    'x2 split feat: {0}'.format(x2_split),
                    'rule score {0}'.format(tree.scores[i])]
    msg_contents = msg_contents + rule_message
    perf_message = []
    for metric in config.PERF_METRICS:
        metric_msg = [
            get_metric_from_tree(tree, metric, i, 'train'),
            get_metric_from_tree(tree, metric, i, 'test')
        ]
        msg_contents = msg_contents + metric_msg
    if hierarchy is not None:
        msg_contents = msg_contents + ['hierarchy node {0}'.format(tree.hierarchy_node[i])]
    msg = "\n".join(msg_contents)
    if verbose:
        print msg
    if ofp is not None:
        ofp.write(msg.strip() + "\n")

### log prints to STDERR
log = Logger()

### Label Functions 
##########################################

# Get method label added to config.OUTPUT_PREFIX
def get_method_label():
    if config.TUNING_PARAMS.use_stable:
        stable_label='stable'
    else:
        stable_label='non_stable'
    if config.TUNING_PARAMS.use_stumps:
        method='stumps'
    else:
        method='adt'
    method_label = '{0}_{1}'.format(method, stable_label)
    return method_label

### Save Tree State 
##########################################

def save_tree_state(tree, pickle_file):
    with gzip.open(pickle_file,'wb') as f:
        pickle.dump(obj=tree, file=f)

def load_tree_state(pickle_file):
    with gzip.open(pickle_file,'rb') as f:
        tree = pickle.load(f)

### Calculation Functions
##########################################

def calc_score(tree, rule_weights, rule_train_index):
    rule_score = 0.5*np.log((
        element_mult(rule_weights.w_pos, rule_train_index).sum()+config.TUNING_PARAMS.epsilon)/
        (element_mult(rule_weights.w_neg, rule_train_index).sum()+config.TUNING_PARAMS.epsilon))
    return rule_score

def calc_loss(wpos, wneg, wzero):
    loss = 2*np.sqrt(element_mult(wpos, wneg))+wzero
    return loss

def calc_margin(y, pred_test):
    # (Y * predicted value (h(x_i))
    margin = element_mult(y, pred_test)
    return margin.sum()


### Matrix Operations
##########################################

# Element-wise  multiplication
def element_mult(matrix1, matrix2):
    if isinstance(matrix1, csr.csr_matrix) and isinstance(matrix2, csr.csr_matrix):
        return matrix1.multiply(matrix2)
    elif isinstance(matrix1, np.ndarray) and isinstance(matrix2, np.ndarray):
        return np.multiply(matrix1, matrix2)
    else:
        assert False, "Inconsistent matrix formats '%s' '%s'" % (type(matrix1), type(matrix2))

# Matrix multiplication
def matrix_mult(matrix1, matrix2):
    if isinstance(matrix1, csr.csr_matrix) and isinstance(matrix2, csr.csr_matrix):
        return matrix1.dot(matrix2)
    elif isinstance(matrix1, np.ndarray) and isinstance(matrix2, np.ndarray):
        return np.dot(matrix1, matrix2)
    else:
        assert False, "Inconsistent matrix formats '%s' '%s'" % (type(matrix1), type(matrix2))

# Convert type of matrix1 to match matrix2 if mismatch is between sparse and numpy array
def convert_type_to_match(matrix1, matrix2):
    if type(matrix1) == type(matrix2):
        return matrix1
    elif isinstance(matrix1,csr_matrix) and isinstance(matrix2, np.ndarray):
        matrix1_new = matrix1.toarray()
    elif isinstance(matrix1,np.ndarray) and isinstance(matrix2, csr_matrix):
        matrix1_new = csr_matrix(matrix1)
    return matrix1_new

### Randomization Functions
##########################################

### Takes a data class object (y, x1, x2) and shuffle the data (in the same proportions)
def shuffle_data_object(obj):
    shuffle_obj = copy.deepcopy(obj)
    if shuffle_obj.sparse:
        shuffle_obj.data = sklearn.utils.shuffle(shuffle_obj.data, replace=False, random_state=1)
    else:
        random.seed(1)
        shuffle_obj.data = np.random.permutation(shuffle_obj.data.ravel()).reshape(shuffle_obj.data.shape)
    return shuffle_obj

### Cluster Regulators
##########################################

import scipy.cluster.hierarchy as hier
import scipy.spatial.distance as dist

# Get cluster assignments based on euclidean distance + complete linkage
def get_data_clusters(data, max_distance=0):
    d = dist.pdist(data, 'euclidean') 
    l = hier.linkage(d, method='complete')
    ordered_data = data[hier.leaves_list(l),:]
    flat_clusters = hier.fcluster(l, t=max_distance, criterion='distance')
    print 'Compressing data: reduced {0} entries to {1} based on max distance {2}'.format(
        data.shape[0], len(np.unique(flat_clusters)), max_distance)
    return(flat_clusters)

# Compress data by taking average of elements in cluster
def regroup_data_by_clusters(data, clusters):
    new_data = np.zeros((len(np.unique(clusters)),data.shape[1]))
    for clust in np.unique(clusters):
        new_feat = np.apply_along_axis(np.mean, 0, data[clusters==clust,:])
        # clusters are 1-based, allocate into 0-based array
        new_data[clust-1,:]=new_feat
    return(new_data)

# Re-write labels by concatenating original labels
def regroup_labels_by_clusters(labels, clusters):
    new_labels = ['na']*len(np.unique(clusters))
    for clust in np.unique(clusters):
        new_label = '|'.join(labels[clusters==clust])
        # clusters are 1-based, allocate into 0-based array
        new_labels[clust-1]=new_label
    return(new_labels)

# Re-cast x2 object with compressed regulator data and labels
def compress_regulators(x2_obj):
    data = x2_obj.data.toarray().T if x2_obj.sparse else x2_obj.data.T
    labels = x2_obj.col_labels
    clusters = get_data_clusters(data, max_distance=0)
    new_data = regroup_data_by_clusters(data, clusters)
    new_labels = regroup_labels_by_clusters(labels, clusters)
    x2_obj.data = csr_matrix(new_data.T) if x2_obj.sparse else new_data.T
    x2_obj.col_labels = np.array(new_labels)
    x2_obj.num_row = x2_obj.data.shape[0]
    x2_obj.num_col = x2_obj.data.shape[1]
    return(x2_obj)

def get_best_split_regulator(tree, x2, best_split):
    if tree.split_x2[best_split] == 'root':
        best_split_regulator = 'root'
    else:
        best_split_regulator = x2.col_labels[tree.split_x2[best_split]]
    return best_split_regulator

# Re-cast x1 object with compressed regulator data and labels
# def compress_motifs(x1_obj):
#     data = x2_obj.data.toarray().T if x2_obj.sparse else x2_obj.data.T
#     labels = x2_obj.col_labels
#     clusters = get_data_clusters(data, max_distance=0)
#     new_data = regroup_data_by_clusters(data, clusters)
#     new_labels = regroup_labels_by_clusters(labels, clusters)
#     x2_obj.data = csr_matrix(new_data.T) if x2_obj.sparse else new_data.T
#     x2_obj.col_labels = np.array(new_labels)
#     x2_obj.num_row = x2_obj.data.shape[0]
#     x2_obj.num_col = x2_obj.data.shape[1]
#     return(x2_obj)

### Stabilizatoin: sum of sqr sqr sums 
##########################################


def calc_sqrt_sum_sqr_sqr_sums(data):
    """
    data should be a raveled 1D array
    """
    result = np.sqrt((data**2).sum()/(data.sum()**2))
    return result

# def calc_sqrt_sum_sqr_sqr_sums(data):
#     # find all non-zero entries
#     sum_squared_values = 0
#     sum_values = 0
#     for i in range(data.shape[0]):
#         value = data[i] 
#         sum_squared_values += value*value
#         sum_values += value
#     return np.sqrt(sum_squared_values/(sum_values**2))

import random
import math
from typing import List
from argparse import Namespace
from collections import defaultdict

import numpy as np
from tqdm import tqdm
from torch.utils.data.dataset import Dataset

from .scaler import StandardScaler
from chemprop.features import morgan_fingerprint, rdkit_2d_features


class SparseNoneArray:
    def __init__(self, targets: List[float]):
        self.length = len(targets)
        self.targets = defaultdict(lambda: None, {i: x for i, x in enumerate(targets) if x is not None})
    
    def __len__(self):
        return self.length
    
    def __getitem__(self, i):
        if i >= self.length:
            raise IndexError
        return self.targets[i]


class MoleculeDatapoint:
    def __init__(self,
                 line: List[str],
                 args: Namespace,
                 features: np.ndarray = None,
                 use_compound_names: bool = False):
        """
        Initializes a MoleculeDatapoint.

        :param line: A list of strings generated by separating a line in a data CSV file by comma.
        :param features: A numpy array containing additional features (ex. Morgan fingerprint).
        :param features_generator: The method of generating additional features.
        :param use_compound_names: Whether the data CSV includes the compound name on each line.
        :param predict_features: Whether the targets should be the features instead of the targets on the CSV line.
        """
        features_generator = args.features_generator if args is not None else None
        predict_features = args.predict_features if args is not None else False
        sparse = args.sparse if args is not None else False

        if features is not None and features_generator is not None:
            raise ValueError('Currently cannot provide both loaded features and a features generator.')

        if use_compound_names:
            self.compound_name = line[0]  # str
            line = line[1:]
        else:
            self.compound_name = None

        self.smiles = line[0]  # str
        self.features = features  # np.ndarray
        if self.features is not None and len(self.features.shape) > 1:
            self.features = np.squeeze(self.features)

        # Generate additional features if given a generator
        if features_generator is not None:
            self.features = []
            for fg in features_generator:
                if fg == 'morgan':
                    self.features.append(morgan_fingerprint(self.smiles))  # np.ndarray
                elif fg == 'morgan_count':
                    self.features.append(morgan_fingerprint(self.smiles, use_counts=True))
                elif fg == 'rdkit_2d':
                    self.features.append(rdkit_2d_features(self.smiles))
                else:
                    raise ValueError('features_generator type "{}" not supported.'.format(fg))
            self.features = np.concatenate(self.features)
        
        if args is not None and args.dataset_type == 'unsupervised':
            self.num_tasks = 1 #TODO could try doing "multitask" with multiple different clusters?
            self.targets = [None]
        else:
            if predict_features:
                self.targets = self.features.tolist()  # List[float]
            else:
                self.targets = [float(x) if x != '' else None for x in line[1:]]  # List[Optional[float]]

            self.num_tasks = len(self.targets)  # int

            if sparse:
                self.targets = SparseNoneArray(self.targets)

    def set_targets(self, targets): # for unsupervised pretraining only
        self.targets = targets

class MoleculeDataset(Dataset):
    def __init__(self, data: List[MoleculeDatapoint]):
        self.data = data
        self.scaler = None

    def compound_names(self):
        if self.data[0].compound_name is None:
            return None

        return [d.compound_name for d in self.data]

    def smiles(self):
        return [d.smiles for d in self.data]

    def features(self):
        if self.data[0].features is None:
            return None

        return [d.features for d in self.data]

    def targets(self):
        return [d.targets for d in self.data]

    def num_tasks(self):
        return self.data[0].num_tasks

    def shuffle(self, seed: int = None):
        if seed is not None:
            random.seed(seed)
        random.shuffle(self.data)
    
    def chunk(self, num_chunks: int, seed: int = None):
        self.shuffle(seed)
        datasets = []
        chunk_len = math.ceil(len(self.data) / num_chunks)
        for i in range(num_chunks):
            datasets.append(MoleculeDataset(self.data[i * chunk_len:(i + 1) * chunk_len]))
        return datasets
    
    def normalize_features(self, scaler=None):
        if self.data[0].features is None:
            return None

        if scaler is not None:
            self.scaler = scaler
        else:
            if self.scaler is not None:
                scaler = self.scaler
            else:
                features = np.vstack([d.features for d in self.data])
                scaler = StandardScaler(replace_nan_token=0)
                scaler.fit(features)
                self.scaler = scaler

        for d in self.data:
            d.features = scaler.transform(d.features.reshape(1, -1))
        return scaler
    
    def set_targets(self, targets): # for unsupervised pretraining only
        assert len(self.data) == len(targets) # assume user kept them aligned
        for i in range(len(self.data)):
            self.data[i].set_targets(targets[i])

    def __len__(self):
        return len(self.data)

    def __getitem__(self, item):
        return self.data[item]

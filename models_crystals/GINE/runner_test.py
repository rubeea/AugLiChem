import os
import yaml
import shutil
import sys
import socket
import torch
import numpy as np
import pandas as pd
from datetime import datetime
import warnings
from torch import nn
import torch.nn.functional as F
from torch.utils.tensorboard import SummaryWriter
from sklearn.metrics import roc_auc_score, mean_squared_error, mean_absolute_error

from dataset.data_wrapper_test import CrystalDatasetWrapper
from model.gin import GINet

warnings.simplefilter("ignore",UserWarning)
def _save_config_file(model_checkpoints_folder):
    if not os.path.exists(model_checkpoints_folder):
        os.makedirs(model_checkpoints_folder)
        shutil.copy('./config_test.yaml', os.path.join(model_checkpoints_folder, 'config_test.yaml'))


class Runner(object):
    def __init__(self, dataset, config):
        self.config = config
        self.device = self._get_device()

        current_time = datetime.now().strftime('%b%d_%H-%M-%S')
        # task_name = config['dataset']['data_dir'][5:-5]
        dir_name = current_time
        log_dir = os.path.join('runs', dir_name)
        self.writer = SummaryWriter(log_dir=log_dir)
        self.dataset = dataset
        if config['dataset']['task'] == 'classification':
            self.criterion = nn.BCEWithLogitsLoss()
        elif config['dataset']['task'] == 'regression':
            self.criterion = nn.MSELoss()
            # self.criterion = nn.L1Loss()

    def _get_device(self):
        if torch.cuda.is_available() and self.config['gpu'] != 'cpu':
            device = self.config['gpu']
            torch.cuda.set_device(device)
        else:
            device = 'cpu'
        print("Running on:", device)

        return device

    def _step(self, model, data, n_iter):
        __, pred = model(data)
        loss = self.criterion(pred, data.y)
        
        return loss

    # def _load_pre_trained_weights(self):
    #     try:
    #         model = GNNModel(**self.config["model"]).to(self.device)
    #         print(self.config['fine_tune_from'])
    #         checkpoints_folder = os.path.join(self.config['fine_tune_from'], 'checkpoints')
    #         print(checkpoints_folder)
    #         state_dict = torch.load(os.path.join(checkpoints_folder, 'model.pth'), map_location=self.device)
    #         model.load_state_dict(state_dict)
    #         print("Loaded pre-trained model with success.")
    #     except FileNotFoundError:
    #         print("Pre-trained weights not found. Training from scratch.")

    #     return model

    def _test(self, test_loader):
        # test steps
        model = GNNModel(**self.config["model"]).to(self.device)
        checkpoints_folder = os.path.join(self.config['fine_tune_from'], 'checkpoints')
        #model_path = os.path.join(self.writer.log_dir, 'checkpoints', 'model.pth')
        state_dict = torch.load(os.path.join(checkpoints_folder, 'model.pth'), map_location=self.device)
        model.load_state_dict(state_dict)
        print("Loaded trained model with success.")

        # test steps
        predictions = []
        labels = []
        with torch.no_grad():
            model.eval()

            test_loss = 0.0
            num_data = 0
            for bn, (data) in enumerate(test_loader):
                data = data.to(self.device)
                __, pred = model(data)
                loss = self._step(model, data, bn)

                test_loss += loss.item() * data.y.size(0)
                num_data += data.y.size(0)

                if self.device == 'cpu':
                    predictions.extend(pred.detach().numpy())
                    labels.extend(labels.flatten().numpy())
                else:
                    predictions.extend(pred.cpu().detach().numpy())
                    labels.extend(data.y.cpu().flatten().numpy())

            test_loss /= num_data

        if self.config['dataset']['task'] == 'regression':
            predictions = np.array(predictions)
            labels = np.array(labels)
            predictions = test_loader.dataset.scaler.inverse_transform(predictions)
            labels = test_loader.dataset.scaler.inverse_transform(labels)
            # self.rmse = mean_squared_error(labels, predictions, squared=False)
            self.mae = mean_absolute_error(labels, predictions)
            print('Test loss:', test_loss)
            # print('Test RMSE:', self.rmse)
            print('Test MAE:', self.mae)

            return test_loss, self.mae

        elif self.config['dataset']['task'] == 'classification': 
            predictions = np.array(predictions)
            predictions = 1 / (1 + np.exp(-predictions)) 
            labels = np.array(labels)
            self.roc_auc = roc_auc_score(labels, predictions)
            print('Test loss:', test_loss)
            print('Test ROC AUC:', self.roc_auc)
            
            return test_loss, self.roc_auc


if __name__ == "__main__":
    
    config = yaml.load(open("config_test.yaml", "r"), Loader=yaml.FullLoader)
    print(config)

    if config['model_type'] == 'gin':
        from model.gin import GINet as GNNModel
    elif config['model_type'] == 'dimenet':
        from model.dimenet import DimeNet as GNNModel
    else:
        raise ValueError('Undefined GNN model')

    if 'Augmented_lanths' in config['dataset']['data_dir']:
        config['dataset']['task'] = 'regression'
        task_name = 'lanths'
    elif 'Augmented_abx3_cifs' in config['dataset']['data_dir']:
        config['dataset']['task'] = 'regression'
        task_name = 'perovskites'
    elif 'Augmented_band' in config['dataset']['data_dir']:
        config['dataset']['task'] = 'regression'
        task_name = 'band'
    elif 'Augmented_FE' in config['dataset']['data_dir']:
        config['dataset']['task'] = 'regression'
        task_name = 'FE'
    elif 'Augmented_fermi' in config['dataset']['data_dir']:
        config['dataset']['task'] = 'regression'
        task_name = 'fermi'

    elif 'abx3_cifs' in config['dataset']['data_dir']:
        config['dataset']['task'] = 'regression'
        task_name = 'perovskites'
    elif 'band' in config['dataset']['data_dir']:
        config['dataset']['task'] = 'regression'
        task_name = 'band'
    elif 'FE' in config['dataset']['data_dir']:
        config['dataset']['task'] = 'regression'
        task_name = 'FE'
    elif 'fermi' in config['dataset']['data_dir']:
        config['dataset']['task'] = 'regression'
        task_name = 'fermi'
    
    elif 'lanths' in config['dataset']['data_dir']:
        config['dataset']['task'] = 'regression'
        task_name = 'lanths'
    else:
        raise ValueError('Undefined dataset')

    fold_num = 5
    models_fe  = ["./runs/FE/Jul31_19-18-54","./runs/FE/Aug01_08-24-44","./runs/FE/Aug01_21-34-14","./runs/FE/Aug02_10-45-47","./runs/FE/Aug02_23-58-02"]
    models_band = ["./runs/band/Sep13_13-44-04","./runs/band/Sep15_19-22-11","./runs/band/Sep16_09-38-58","./runs/band/Sep16_09-38-58","./runs/band/Sep17_14-01-12"]
    models_perov = ["./runs/Perov/Aug08_09-56-36","./runs/Perov/Aug08_12-16-39","./runs/Perov/Aug08_14-36-10","./runs/Perov/Aug08_16-55-37","./runs/Perov/Aug08_19-15-08"]
    models_fermi = ["./runs/Fermi/Aug04_05-50-14","./runs/Fermi/Aug04_18-58-12","./runs/Fermi/Aug05_08-24-39","./runs/Fermi/Aug05_21-25-25","./runs/Fermi/Aug06_10-22-32"]
    models_lanths = ["./runs/Lanths/Jul30_21-53-11","./runs/Lanths/Jul30_23-20-19","./runs/Lanths/Jul31_00-47-17","./runs/Lanths/Jul31_02-13-27","./runs/Lanths/Jul31_03-38-57"]

    for i in range(len(models_lanths)):
        config['fine_tune_from'] = models_lanths[i]
        print(config)
        curr_fold = i
        dataset = CrystalDatasetWrapper(config['batch_size'], **config['dataset'],fold = curr_fold)

        runner = Runner(dataset, config)
        loss, metric = runner._test(test_loader = dataset.get_data_loaders())
        
        df = pd.DataFrame([[loss, metric]])
        os.makedirs('experiments', exist_ok=True)
        df.to_csv('experiments/{}_{}_{}.csv'.format(config['model_type'], task_name,fold_num), index=False, mode='a', header=False)
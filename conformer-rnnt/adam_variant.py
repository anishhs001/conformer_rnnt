# -*- coding: utf-8 -*-
"""adam_variant.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1NZNHsRCpRFtyKHEZRK_-2J5A5dMJ7vTx
"""

import torch
from torch.optim import Optimizer
import torch
import torch.nn as nn
import torch.nn.functional as F
import math
import numpy as np

#Custom Adam Optimizer - extension of Optimizer class
#Imporved upon the code in https://github.com/thetechdude124/Adam-Optimization-From-Scratch/blob/master/CustomAdam.py
class ScaledAdam(Optimizer):
    """
    A custom implementation of the Adam optimizer. Defaults used are as recommended in https://arxiv.org/abs/1412.6980

    Params:
    lr (float): the effective upperbound of the optimizer step in most cases (size of step). DEFAULT - 0.001.
    bias_m1 (float): bias for the first moment estimate. DEFAULT - 0.9
    bias_m2 (float): bias for the second uncentered moment estimate, DEFAULT - 0.999.
    epsilon (float): small number added to prevent division by zero, DEFAULT - 10e-8.
    bias_correction (bool): whether the optimizer should correct for the specified biases when taking a step. DEFAULT - TRUE.
    """
    #Initialize optimizer with parameters
    def __init__(self, params, lr = 0.00001, bias_m1 = 0.9, bias_m2 = 0.999, epsilon = 10e-8, bias_correction = True, scaling = True):
        self.scaling = scaling
        #Check if lr and biases are invalid (negative)
        if lr < 0:
            raise ValueError("Invalid lr [{}]. Choose a positive lr".format(lr))
        if bias_m1 < 0 or bias_m2 < 0 and bias_correction:
            raise ValueError("Invalid bias parameters [{}, {}]. Choose positive bias parameters.".format(bias_m1, bias_m2))
        #Declare dictionary of default values for optimizer initialization
        DEFAULTS = dict(lr = lr, bias_m1 = bias_m1, bias_m2 = bias_m2, epsilon = epsilon, bias_correction = bias_correction)
        #Initialize the optimizer
        super(ScaledAdam, self).__init__(params, DEFAULTS)

    #Step method (for updating parameters)
    def step(self, closure = None):
        #Set loss to none
        loss = None
        #If the closure is set to True, set the loss to the closure function
        if closure is not None:
            loss = closure()

        #Iterate over "groups" of parameters (layers of parameters in the network) to begin processing and computing the next set of params
        for group in self.param_groups:
            #Iterate over individual parameters
            for param in group["params"]:
                #Check if gradients have been computed for each parameter
                #If not - if there are no gradients - then skip the parameter
                if param.grad == None:
                    continue
                else:
                  gradients = param.grad.data
                #Use Adam optimization method - first, define all the required arguments for the parameter if we are on the first step
                state = self.state[param]

                # State initialization by checking if this is the first step - if not, increment the current step
                if 'step' not in state:
                    state['step'] = 0
                    state['first_moment_estimate'] = torch.zeros_like(param.data)
                    state['second_moment_estimate'] = torch.zeros_like(param.data)

                state['step'] += 1

                first_moment_estimate = state['first_moment_estimate']
                second_moment_estimate = state['second_moment_estimate']

                beta1, beta2 = group['bias_m1'], group['bias_m2']
                lr, epsilon = group['lr'], group['epsilon']

                # Compute the first moment estimate (moving average of the gradients)
                first_moment_estimate.mul_(beta1).add_(gradients, alpha=(1 - beta1))
                # Compute the second moment estimate (moving average of the squared gradients)
                second_moment_estimate.mul_(beta2).addcmul_(gradients, gradients, value=(1 - beta2))

                # Bias correction
                if group['bias_correction']:
                    bias_correction1 = 1 - beta1 ** state['step']
                    bias_correction2 = 1 - beta2 ** state['step']
                    corrected_first_moment = first_moment_estimate / bias_correction1
                    corrected_second_moment = second_moment_estimate / bias_correction2
                else:
                    corrected_first_moment = first_moment_estimate
                    corrected_second_moment = second_moment_estimate

                # Scaling factor for Adam
                if self.scaling:
                    scale_factor = ((1 - beta1) ** 0.5) / (1 - beta2)
                else:
                    scale_factor = 1

                # Compute step size
                lr = lr * scale_factor

                #Next, perform the actual update
                #Multiply the lr a by the quotient of the first moment estimate and the square root of the second moment estimate plus epsilon
                #In other words - theta = theta_{t-1} - a * first_estimate/(sqr(second_estimate) + epsilon)
                denom = corrected_second_moment.sqrt().add_(epsilon)
                param.data.addcdiv_(corrected_first_moment, denom, value=-lr)
        #Return the loss
        return loss
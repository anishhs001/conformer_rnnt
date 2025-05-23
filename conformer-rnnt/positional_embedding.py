# -*- coding: utf-8 -*-
"""positional_embedding.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1HRYfC0uimQO_m3B87LJN2Jmz6mFdbe-N
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import math
import numpy as np
from einops import rearrange

# Creating the Sinusoidal/Absolute Positional Embedding
class absolutepositionalembedding(nn.Module):

    def __init__(self, d_model: int, max_sequence_length = 512, dropout = 0.):
        super().__init__()
        self.d_model = d_model # Dimensionality of the model
        self.seq_len = max_sequence_length # Maximum sequence length
        self.dropout = nn.Dropout(dropout) # Dropout layer to prevent overfitting

        # Creating a positional encoding matrix of shape (seq_len, d_model) filled with zeros
        pe = torch.zeros(max_sequence_length, d_model)

        # Creating a tensor representing positions (0 to seq_len - 1)
        position = torch.arange(0, max_sequence_length, dtype = torch.float).unsqueeze(1) # Transforming 'position' into a 2D tensor['seq_len, 1']

        # Creating the division term for the positional encoding formula
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))

        # Apply sine to even indices in pe
        pe[:, 0::2] = torch.sin(position * div_term)
        # Apply cosine to odd indices in pe
        pe[:, 1::2] = torch.cos(position * div_term)

        # Adding an extra dimension at the beginning of pe matrix for batch handling
        pe = pe.unsqueeze(0)

        # Registering 'pe' as buffer. Buffer is a tensor not considered as a model parameter
        self.register_buffer('pe', pe)

    def forward(self,x):
        # Adding positional encoding to the input tensor X
        x = x + (self.pe[:, :x.shape[1], :])
        return self.dropout(x) # Dropout for regularization

# Creating the Rotary Positional Encoding/Embedding
class rotarypositionalembedding(nn.Module):
  def __init__(self, d_model, base = 10000, dropout = 0.):
    super().__init__()
    self.base = base  # Base term for division
    self.d_model = d_model  # Dimensionality of the model
    self.cos_cached = None  # Cos calculation wrt theta
    self.sin_cached = None  # Sin calculation wrt theta
    self.dropout = nn.Dropout(dropout) # Dropout layer to prevent overfitting

  def _build_cache(self, x: torch.Tensor):
    if self.cos_cached is not None and x.shape[0] <= self.cos_cached.shape[0]:
      # If the values are already computed, then it skips the calculation step
      return
    seq_len = x.shape[1]
    # Calculating theta based on the formula 10000^(−(2(i-1)/d))
    theta = 1. / (self.base ** (torch.arange(0, self.d_model, 2).float() / self.d_model))
    seq_idx = torch.arange(seq_len).float()  # Creating sequence indices
    idx_theta = torch.einsum('n,d->nd', seq_idx, theta)  # Dot product of sequence length m and theta
    idx_theta2 = torch.cat([idx_theta, idx_theta], dim=-1)
    # Computing cosine and sine values of theta
    self.cos_cached = idx_theta2.cos().unsqueeze(0)
    self.sin_cached = idx_theta2.sin().unsqueeze(0)

  def _neg_half(self, x: torch.Tensor):
    d_2 = self.d_model // 2
    # Negating the second half of the tensor and concatenating with the first half
    return torch.cat([-x[:, :, d_2:], x[:, :, :d_2]], dim=-1)

  def forward(self, x: torch.Tensor):
    self._build_cache(x)  # Building cache if not already computed
    x_rope, x_pass = x[..., :self.d_model], x[..., self.d_model:]
    neg_half_x = self._neg_half(x_rope)
    # Calculating using the rotation matrix: x' = x * cos(theta) + (−x * sin(theta))
    x_rope = (x_rope * self.cos_cached[:x.shape[0]]) + (neg_half_x * self.sin_cached[:x.shape[0]])
    x = x + torch.cat((x_rope, x_pass), dim=-1)  # Concatenating transformed and unchanged parts
    return self.dropout(x) # Dropout for regularization


# Creating different Relative Positional Embedding/Encoding

""" from https://github.com/gazelle93/Transformer-Various-Positional-Encoding/tree/main"""

class relativeembedding(nn.Module):
    def __init__(self, d_model, max_position=512):
        super().__init__()
        # Initialize the module with the specified embedding dimension and maximum position
        self.max_position = max_position
        # Define the embeddings table as a learnable parameter
        # The table has a shape of (max_position * 2 + 1, emb_dim)
        self.embeddings_table = nn.Parameter(torch.Tensor(max_position * 2 + 1, d_model))
        # Initialize the values of the embeddings table using Xavier initialization
        nn.init.xavier_uniform_(self.embeddings_table)

    def forward(self, x):
        # x should be of shape (batch_size, seq_len, d_model)
        batch_size, seq_len, _ = x.shape
        if seq_len > self.max_position:
            raise ValueError(f"Sequence length {seq_len} exceeds the maximum position {self.max_position}.")

        # Generate position indices for the sequence length
        position_indices = torch.arange(seq_len).unsqueeze(0).expand(batch_size, seq_len)

        # Get positional embeddings
        embeddings = self.embeddings_table[position_indices]

        # Add positional embeddings to the input tensor
        return x + embeddings

class t5relativeembedding(nn.Module):
    def __init__(self, d_model, max_position=512):
        super().__init__()
        # Initialize the positional embedding table with an embedding layer
        self.max_position = max_position  # Maximum allowed position
        # The embedding table has a size of max_position * max_position and embeds into num_heads dimensions
        self.embeddings_table = nn.Embedding(max_position*max_position, d_model)

    def forward(self, x):
        # x should be of shape (batch_size, seq_len, d_model)
        batch_size, seq_len, _ = x.shape
        if seq_len > self.max_position:
            raise ValueError(f"Sequence length {seq_len} exceeds the maximum position {self.max_position}.")

        # Generate position indices for the sequence length
        position_indices = torch.arange(seq_len).unsqueeze(0).expand(batch_size, seq_len)
        # Clip relative positions to avoid exceeding maximum allowed position
        relative_position_clipped = torch.clamp(position_indices, -self.max_position, self.max_position)
        # Shift the clipped relative positions to ensure they are all non-negative
        final_mat = relative_position_clipped + self.max_position
        # Lookup embeddings for the final relative positions from the embedding table
        embeddings = self.embeddings_table(final_mat)

        return x + embeddings
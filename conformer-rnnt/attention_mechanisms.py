# -*- coding: utf-8 -*-
"""attention_mechanisms.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1N4PGBqf_Cr3wVWXEv4qnQjlvELDAjiU4
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import math
import numpy as np
from einops import rearrange


def create_window_tensor(window_size, percentage_frac):
      # Calculate the number of elements on each side of the center
      num_side_elements = (window_size - 1) // 2

      # Generate decreasing values for the side elements
      side_values = torch.tensor([(1 - percentage_frac) ** i for i in range(num_side_elements, 0, -1)], dtype=torch.float32)

      # Concatenate the side values, center value (1), and reverse of side values
      window_values = torch.cat([side_values, torch.tensor([1.0]), side_values.flip(0)])

      # Ensure the tensor has the correct size (1, window_size)
      window_tensor = window_values.view(1, -1)

      return window_tensor

class DotProductAttention(nn.Module):
    def __init__(self):
        super().__init__()

    def forward(self, queries, keys, values, mask=None, linear_bias = False, include_local_attention = False, local_attention_window = 3, local_attention_dim_vertical = False):
        # Scoring the queries against the keys after transposing the latter, and scaling
        scores = torch.matmul(queries, keys.transpose(-2, -1)) / (keys.size(-1) ** 0.5)
        # Apply mask to the attention scores
        if mask is not None:
          scores = scores.masked_fill(mask, -1e9)

        # Set include_local_attention = True for computing local attention
        if include_local_attention:
          # Define the convolutional kernel
          kernel = create_window_tensor(local_attention_window, 0.3)
          assert len(scores.shape) == 4
          batch_size, heads, height, width = scores.shape
          output_array = torch.empty((batch_size, heads, height, width), dtype=scores.dtype)

          # Calculate padding
          padding_w = (local_attention_window - 1) // 2

          for b in range(batch_size):
              for c in range(heads):
                  if not local_attention_dim_vertical:
                    # Perform 2D convolution with padding to maintain the same shape
                    scores_conv_output = F.conv2d(scores[b,c].transpose(-2, -1).unsqueeze(0).float(),
                                            kernel.unsqueeze(0).unsqueeze(0).float(),
                                            padding=(0, padding_w))

                    # Remove the additional batch and channel dimensions
                    head_output = scores_conv_output.squeeze().transpose(-2, -1)
                  else:
                    # Perform 2D convolution with padding to maintain the same shape
                    scores_conv_output = F.conv2d(scores[b,c].unsqueeze(0).float(),
                                            kernel.unsqueeze(0).unsqueeze(0).float(),
                                            padding=(0, padding_w))

                    # Remove the additional batch and channel dimensions
                    head_output = scores_conv_output.squeeze()
                  output_array[b,c] = head_output
          scores = output_array

        # Set bias = True for including ALiBi to the attention scores
        if linear_bias:
          _, _, _, bias_shape = scores.shape
          beta = nn.Parameter(torch.zeros(bias_shape))
          scores = scores + beta

        # Computing the weights by a softmax operation
        weights = F.softmax(scores, dim=-1)

        attention_output = torch.matmul(weights, values)

        # Computing the attention by a weighted sum of the value vectors
        return attention_output

class MultiHeadAttention(nn.Module):
  def __init__(self, dim, dim_head = 64, heads = 8, dropout = 0., linear_bias = False, include_local_attention = False, local_attention_window = 3, local_attention_dim_vertical = False):
        super().__init__()
        self.heads = heads  # Number of attention heads to use
        self.d_model = dim  # Dimensionality of the model
        self.dim_head = dim_head
        self.linear_bias = linear_bias #Boolean value to include/exclude ALiBi
        self.include_local_attention = include_local_attention #Boolean value to include/exclude local attention
        self.local_attention_window = local_attention_window #Numerical value for a window of local attention
        self.local_attention_dim_vertical = local_attention_dim_vertical #Boolean value to convolute basis the horizontal/vertical direction
        self.attention = DotProductAttention()  # Scaled dot product attention
        self.W_q = nn.Linear(self.d_model, self.heads * self.dim_head)  # Learned projection matrix for the queries
        self.W_k = nn.Linear(self.d_model, self.heads * self.dim_head)  # Learned projection matrix for the keys
        self.W_v = nn.Linear(self.d_model, self.heads * self.dim_head)  # Learned projection matrix for the values
        self.W_o = nn.Linear(self.heads * self.dim_head, self.d_model)  # Learned projection matrix for the multi-head output
        self.dropout = nn.Dropout(dropout)

  def reshape_tensor(self, x, heads, flag):
        if flag:
            # Tensor shape after reshaping and transposing: (batch_size, heads, seq_length, -1)
            x = x.view(x.size(0), x.size(1), self.heads, -1).transpose(1, 2)
        else:
            # Reverting the reshaping and transposing operations: (batch_size, seq_length, d_k)
            x = rearrange(x, "b h t d -> b t (h d)")
        return x

  def forward(self,x, mask=None):
      # Rearrange the queries to be able to compute all heads in parallel
      q_reshaped = self.reshape_tensor(self.W_q(x), self.heads, True)
      # Rearrange the keys to be able to compute all heads in parallel
      k_reshaped = self.reshape_tensor(self.W_k(x), self.heads, True)
      # Rearrange the values to be able to compute all heads in parallel
      v_reshaped = self.reshape_tensor(self.W_v(x), self.heads, True)
      # Compute the multi-head attention output using the reshaped queries, keys, and values
      o_reshaped = self.attention(q_reshaped, k_reshaped, v_reshaped, mask, self.linear_bias, self.include_local_attention, self.local_attention_window, self.local_attention_dim_vertical)
      # Rearrange back the output into concatenated form
      output = self.reshape_tensor(o_reshaped, self.heads, False)
      # Apply one final linear projection to the output to generate the multi-head attention
      output = self.W_o(output)
      output = self.dropout(output)
      return output


class MultiHeadSelfAttention(nn.Module):
    def __init__(self, dim, dim_head = 64, heads=8, dropout = 0., linear_bias = False, include_local_attention = False, local_attention_window = 3, local_attention_dim_vertical = False):
        """
        Implementation of multi-head attention layer of the original transformer model.
        einsum and einops.rearrange is used whenever possible
        Args:
            dim: token's dimension, i.e. word embedding vector size
            heads: the number of distinct representations to learn
            dim_head: the dim of the head. In general dim_head<dim.
            However, it may not necessary be (dim/heads)
        """
        super().__init__()
        self.dim = dim
        self.heads = heads
        self.dim_head = dim_head
        self.inner_dim = self.dim_head * self.heads
        self.to_qvk = nn.Linear(self.dim, self.inner_dim * 3)
        self.W_0 = nn.Linear(self.inner_dim, self.dim)
        self.dropout = nn.Dropout(dropout)
        self.linear_bias = linear_bias #Boolean value to include/exclude ALiBi
        self.include_local_attention = include_local_attention #Boolean value to include/exclude local attention
        self.local_attention_window = local_attention_window #Numerical value for a window of local attention
        self.local_attention_dim_vertical = local_attention_dim_vertical #Boolean value to convolute basis the horizontal/vertical direction
        self.attention = DotProductAttention()  # Scaled dot product attention

    def forward(self, x, mask=None):
        assert x.dim() == 3
        # Step 1
        qkv = self.to_qvk(x)  # [batch, tokens, dim*3*heads]

        # Step 2
        # decomposition to q,v,k and cast to tuple
        # the resulted shape before casting to tuple will be:
        # [3, batch, heads, tokens, dim_head]
        q, k, v = tuple(rearrange(qkv, 'b t (d k h) -> k b h t d ', k=3, h=self.heads))
        # Step 3
        # Calc result per batch and per head h
        output = self.attention(q, k, v, mask, self.linear_bias, self.include_local_attention, self.local_attention_window, self.local_attention_dim_vertical)
        # Step 4. Re-compose: merge heads with dim_head d
        output = rearrange(output, "b h t d -> b t (h d)")
        # Step 6. Apply final linear transformation layer
        output = self.W_0(output)
        output = self.dropout(output)
        return output
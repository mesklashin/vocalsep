# Demucs Model Comparison for French Rap Vocal Separation

This document summarizes the available Demucs v4 and v3 models, focusing on their applicability for separating French rap vocals.

## 🚀 Model Overview

| Model | Architecture | Primary Use Case | SDR (Estimate) | Speed |
| :--- | :--- | :--- | :--- | :--- |
| **`htdemucs`** | Hybrid Transformer | General use, well-balanced | High | Fast |
| **`htdemucs_ft`** | Hybrid Transformer | Maximum quality extraction | Very High | Very Slow |
| **`mdx_extra`** | Hybrid (non-transformer) | Legacy consistency | High | Medium |
| **`mdx_extra_q`** | Quantized Hybrid | Low memory/storage | Medium-High | Fast |
| **`htdemucs_6s`** | Hybrid Transformer | Experimental 6-stem | Variable | Medium |

## 🇫🇷 French Rap Specifics

French Rap presents unique challenges for vocal separation:
1.  **Dense Lyrics & Slang**: High word density can cause "blurring" in the vocal stem if the model isn't precise.
2.  **Heavy Bass/808s**: Rap often has loud low-end frequencies that can bleed into the vocal stem.
3.  **Ad-libs/Backing Vocals**: Demucs generally treats all vocals as one stem, but reverb-heavy ad-libs can sometimes be misclassified as "other".

## 📊 Recommendation for this Project

1.  **Primary Model: `htdemucs`**  
    The default transformer model is the best starting point. It handles transients well, which is crucial for rap percussion and rhythmic vocal delivery.

2.  **Comparison Model: `mdx_extra`**  
    We will use this to verify if the newer Transformer architecture actually outperforms the older Hybrid architecture on "street" recordings which often have non-standard mixing.

3.  **High-Quality Refinement: `htdemucs_ft`**  
    Used for final evaluation if the `htdemucs` output shows significant artifacts.

## 🛠️ Implementation Plan

In Task 2.2, we will implement `separator.py` to allow easy switching between these models for batch processing.

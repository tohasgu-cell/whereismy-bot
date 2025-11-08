from sentence_transformers import SentenceTransformer
import numpy as np
import logging

# Загружаем модель один раз при импорте
logging.info("🔍 Загружаем модель для векторного поиска...")
model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
logging.info("✅ Модель загружена.")

def encode_text(text: str) -> np.ndarray:
    """Преобразует текст в вектор (эмбеддинг) размерности 384."""
    return model.encode(text, convert_to_numpy=True)

def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

def rank_ads_by_query(query_embedding: np.ndarray, ads_with_embeddings: list) -> list:
    """
    ads_with_embeddings: список кортежей (ad_row, embedding)
    Возвращает: [(ad_row, similarity), ...], отсортировано по убыванию
    """
    scored = []
    for ad, emb in ads_with_embeddings:
        sim = cosine_similarity(query_embedding, emb)
        scored.append((ad, sim))
    return sorted(scored, key=lambda x: x[1], reverse=True)
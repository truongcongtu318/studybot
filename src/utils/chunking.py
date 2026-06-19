"""Smart Chunking module.
Implements sentence-boundary chunking with configurable chunk size and overlap.
"""
import re
from typing import List

def smart_chunk(text: str, chunk_size: int = 500, chunk_overlap: int = 100) -> List[str]:
    """Splits text into chunks based on sentence boundaries, keeping size and overlap.
    
    Args:
        text: Input document text.
        chunk_size: Maximum character length of each chunk.
        chunk_overlap: Target overlap between consecutive chunks.
        
    Returns:
        A list of text chunks.
    """
    if not text or not text.strip():
        return []
        
    # Split text into sentences (handles common abbreviations and decimal points reasonably)
    # This regex splits by sentence terminators followed by whitespace.
    sentence_endings = re.compile(r'(?<=[.!?])\s+')
    sentences = sentence_endings.split(text)
    
    chunks = []
    current_chunk_sentences = []
    current_length = 0
    
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
            
        sentence_length = len(sentence)
        
        # If a single sentence is larger than chunk_size, we split it by words
        if sentence_length > chunk_size:
            # Handle exceptionally long sentence
            if current_chunk_sentences:
                chunks.append(" ".join(current_chunk_sentences))
                current_chunk_sentences = []
                current_length = 0
            
            words = sentence.split(" ")
            word_chunk = []
            word_len = 0
            for word in words:
                if word_len + len(word) + 1 > chunk_size:
                    chunks.append(" ".join(word_chunk))
                    # Retain overlap words
                    overlap_words = word_chunk[-max(1, len(word_chunk)//5):] if len(word_chunk) > 2 else []
                    word_chunk = overlap_words + [word]
                    word_len = sum(len(w) + 1 for w in word_chunk)
                else:
                    word_chunk.append(word)
                    word_len += len(word) + 1
            if word_chunk:
                chunks.append(" ".join(word_chunk))
            continue

        if current_length + sentence_length + (1 if current_chunk_sentences else 0) > chunk_size:
            # Chunk is full, finalize it
            chunk_text = " ".join(current_chunk_sentences)
            chunks.append(chunk_text)
            
            # Create overlap
            # Find sentences to carry over to the next chunk based on chunk_overlap
            overlap_sentences = []
            overlap_len = 0
            for s in reversed(current_chunk_sentences):
                if overlap_len + len(s) + 1 <= chunk_overlap:
                    overlap_sentences.insert(0, s)
                    overlap_len += len(s) + 1
                else:
                    break
            
            current_chunk_sentences = overlap_sentences + [sentence]
            current_length = sum(len(s) + 1 for s in current_chunk_sentences)
        else:
            current_chunk_sentences.append(sentence)
            current_length += sentence_length + (1 if len(current_chunk_sentences) > 1 else 0)
            
    if current_chunk_sentences:
        chunks.append(" ".join(current_chunk_sentences))
        
    return chunks

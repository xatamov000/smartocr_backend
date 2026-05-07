"""
Avtomatik Label Generator
Dataset.csv ni ochib, label ustunini avtomatik to'ldiradi
"""

import pandas as pd
import re

def auto_label_line(row):
    """
    Har bir qator uchun avtomatik label aniqlash
    """
    text = str(row.get('text', '')).strip()
    rel_height = float(row.get('rel_height', 1.0))
    uppercase_ratio = float(row.get('uppercase_ratio', 0.0))
    starts_symbol = int(row.get('starts_symbol', 0))
    is_numbered = int(row.get('is_numbered', 0))
    word_count = int(row.get('word_count', 0))
    ends_colon = int(row.get('ends_colon', 0))
    
    # Qoidalar
    
    # 1. Bullet list
    if starts_symbol == 1:
        return 'bullet'
    
    # 2. Numbered list
    if is_numbered == 1:
        return 'numbered'
    
    # 3. Katta sarlavha
    if rel_height >= 1.6 and word_count <= 12:
        return 'heading1'
    
    # 4. Kichik sarlavha
    if rel_height >= 1.3 and uppercase_ratio >= 0.5 and word_count <= 15:
        return 'heading2'
    
    # 5. Hammasi katta harf
    if uppercase_ratio >= 0.85 and 1 <= word_count <= 10:
        return 'heading2'
    
    # 6. Ikki nuqta bilan tugaydi
    if ends_colon == 1 and word_count <= 8:
        return 'heading2'
    
    # 7. Oddiy abzats
    return 'paragraph'


def main():
    print("Avtomatik label generator")
    print("="*50)
    
    # CSV yuklash
    df = pd.read_csv('dataset.csv', encoding='utf-8-sig')
    
    print(f"Jami qatorlar: {len(df)}")
    
    # Label ustunini to'ldirish
    df['label'] = df.apply(auto_label_line, axis=1)
    
    # Statistika
    print("\nLabel taqsimoti:")
    for label, count in df['label'].value_counts().items():
        print(f"  {label:12s} {count:5d} qator")
    
    # Saqlash
    df.to_csv('dataset_labeled.csv', index=False, encoding='utf-8-sig')
    
    print("\n" + "="*50)
    print("Tayyor! dataset_labeled.csv saqlandi")
    print("\nEndi Excel da ochib tekshiring:")
    print("  - Noto'g'ri labellarni to'g'rilang")
    print("  - Keyin train_model.py ishga tushiring")

if __name__ == "__main__":
    main()
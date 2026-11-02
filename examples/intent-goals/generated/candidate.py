from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

def build_pipeline(config):
    text_transformer = ColumnTransformer([
        ('tfidf', TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=30000), config['text_features'][0])
    ])

    pipeline = Pipeline([
        ('text_preprocessing', text_transformer),
        ('classifier', LogisticRegression(C=4.0, max_iter=500, random_state=42, class_weight='balanced'))
    ])

    return pipeline
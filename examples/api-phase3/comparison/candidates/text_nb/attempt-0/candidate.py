from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer

def build_pipeline(config):
    text_transformer = ColumnTransformer([
        ('tfidf', TfidfVectorizer(
            ngram_range=(1, 2),
            sublinear_tf=True,
            max_features=30000
        ), config['text_features'][0])
    ])

    pipeline = Pipeline([
        ('preprocessor', text_transformer),
        ('classifier', MultinomialNB(alpha=0.1))
    ])

    return pipeline
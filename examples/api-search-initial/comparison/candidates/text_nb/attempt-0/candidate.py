from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB

def build_pipeline(config):
    text_transformer = ColumnTransformer([
        ('tfidf', TfidfVectorizer(), config['text_features'][0])
    ])

    pipeline = Pipeline([
        ('preprocessor', text_transformer),
        ('classifier', MultinomialNB(alpha=0.1))
    ])

    return pipeline
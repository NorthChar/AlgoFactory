from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

def build_pipeline(config):
    text_transformer = ColumnTransformer([
        ('tfidf', TfidfVectorizer(), config['text_features'][0])
    ])

    pipeline = Pipeline([
        ('preprocessor', text_transformer),
        ('classifier', LogisticRegression(random_state=config['seed']))
    ])

    return pipeline
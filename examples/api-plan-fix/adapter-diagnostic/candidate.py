from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

def build_pipeline(config):
    pipeline = Pipeline([
        ('text', ColumnTransformer([('tfidf', TfidfVectorizer(
            ngram_range=(1, 2),
            sublinear_tf=True,
            max_features=30000
        ), config['text_features'][0])])),
        ('logreg', LogisticRegression(
            C=4.0,
            max_iter=500,
            random_state=config['seed']
        ))
    ])
    return pipeline
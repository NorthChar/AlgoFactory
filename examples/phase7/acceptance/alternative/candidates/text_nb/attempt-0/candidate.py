from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline


def build_pipeline(config):
    preprocess = ColumnTransformer([
        ("text", TfidfVectorizer(ngram_range=(1, 1), sublinear_tf=True, max_features=10000), config["text_features"][0])
    ])
    model = MultinomialNB(alpha=0.5)
    return Pipeline([("preprocess", preprocess), ("model", model)])

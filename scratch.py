from sense import SenseEmbedding, logl_loss;
from wordvec import WordEmbedding;
from l2c import L2CEmbedding, logl_loss;
from keras.models import Sequential;
from keras.utils.np_utils import to_categorical
import inspect
import cPickle
#model = Sequential()
#model.add(SenseEmbedding(1000, 100, 3, 4))
from keras.utils.generic_utils import Progbar
#model.compile(loss='mse', optimizer='rmsprop')

import theano
theano.config.optimizer = 'None'
theano.config.exception_verbosity ='high'

from keras.preprocessing import text, sequence
import logging


import os, re, json
import random
from keras.utils import np_utils, generic_utils
import numpy as np


logging.basicConfig(filename="sense_vectors.log",level=logging.INFO)
log = logging.getLogger("ex")
data_path = "hn-dump/HNCommentsAll.1perline.json"
html_tags = re.compile(r'<.*?>')
to_replace = [('&#x27;', "'")]
hex_tags = re.compile(r'&.*?;')

def get_class_that_defined_method(meth):
    for cls in inspect.getmro(meth.im_class):
        if meth.__name__ in cls.__dict__: 
            return inspect.getfile(cls)
    return None

def clean_comment(comment):
    c = str(comment.encode("utf-8"))
    c = html_tags.sub(' ', c)
    for tag, char in to_replace:
        c = c.replace(tag, char)
        c = hex_tags.sub(' ', c)
    return c


def text_generator(path=data_path):
    f = open(path)
    for i, l in enumerate(f):
        comment_data = json.loads(l)
        comment_text = comment_data["comment_text"]
        comment_text = clean_comment(comment_text)
        if (i % 50000) == 100:
            break
        yield comment_text
    f.close()

def skipgrams(sequence, vocabulary_size,
              window_size=4, negative_samples=1., shuffle=True,
              categorical=False, sampling_table=None):
    '''Take a sequence (list of indexes of words),
    returns couples of [word_index, other_word index] and labels (1s or 0s),
    where label = 1 if 'other_word' belongs to the context of 'word',
    and label=0 if 'other_word' is ramdomly sampled
    # Arguments
        vocabulary_size: int. maximum possible word index + 1
        window_size: int. actually half-window.
            The window of a word wi will be [i-window_size, i+window_size+1]
        negative_samples: float >= 0. 0 for no negative (=random) samples.
            1 for same number as positive samples. etc.
        categorical: bool. if False, labels will be
            integers (eg. [0, 1, 1 .. ]),
            if True labels will be categorical eg. [[1,0],[0,1],[0,1] .. ]
    # Returns
        couples, lables: where `couples` are int pairs and
            `labels` are either 0 or 1.
    # Notes
        By convention, index 0 in the vocabulary is
        a non-word and will be skipped.
    '''
    couples = []
    labels = []
    dict_of_contexts = {}

    for i, wi in enumerate(sequence):
        if not wi:
            continue
        if sampling_table is not None:
            if sampling_table[wi] < random.random():
                continue

# TODO: ASSUMES EACH WORD OCCURS ATMOST ONCE PER SENTENCE
               
        window_start = max(0, i-window_size)
        window_end = min(len(sequence), i+window_size+1)
        to_add = sequence[window_start : i] + sequence[i+1: window_end]
        while (len(to_add) != 2*window_size + 1):
            to_add.append(0)

        dict_of_contexts[wi] = to_add
        for j in range(window_start, window_end):
            if j != i:
                wj = sequence[j]
                if not wj:
                    continue
                couples.append([wi, wj, j- window_start])
                if categorical:
                    labels.append([0,1])
                else:
                    labels.append(1)

# TODO: SAMPLING OF NEGATIVE EXAMPLES SHOULD BE FROM A DIFFERENT DISTRIUBTION D^{3/4} WHERE D IS THE WORD DISTRIBUTION
    if negative_samples > 0:
        nb_negative_samples = int(len(labels) * negative_samples)
        words = [c[0] for c in couples]
        random.shuffle(words)

        couples += [[words[i %len(words)], random.randint(1, vocabulary_size-1), -1] for i in range(nb_negative_samples)]
        if categorical:
            labels += [[1,0]]*nb_negative_samples
        else:
            labels += [0]*nb_negative_samples

    if shuffle:
        seed = random.randint(0,10e6)
        random.seed(seed)
        random.shuffle(couples)
        random.seed(seed)
        random.shuffle(labels)
    couples_augmented = [[x,y,z]+dict_of_contexts[x] for (x, y, z) in couples]
    return couples_augmented, labels
    # return couples, labels

if __name__ == "__main__":
    model = Sequential()
    vocab_size = 50000
    dim = 256
    context_size = 4
    num_senses = 3
    nb_epoch = 10
    model.add(SenseEmbedding(input_dim = 2*context_size + 2, vocab_dim = vocab_size+1, vector_dim = dim, num_senses = 3))
    model.compile(loss=logl_loss, optimizer='adagrad')
    fit = 1
    tokenizer_fname = "HN_tokenizer.pkl"
    if fit:
        print("Fit tokenizer...")
        tokenizer = text.Tokenizer(nb_words=vocab_size)
        tokenizer.fit_on_texts(text_generator())
        

        print("Save tokenizer...")
        f = open(tokenizer_fname, "wb")

        cPickle.dump(tokenizer, f, protocol=cPickle.HIGHEST_PROTOCOL)
        f.close()

    else:
        print('Load tokenizer...')
        f = open(tokenizer_fname, "rb")
        tokenizer = cPickle.load(f)
        f.close()


    sampling_table = sequence.make_sampling_table(vocab_size)

    for e in range(nb_epoch):
        print('-'*40)
        print('Epoch', e)
        print('-'*40)

        progbar = Progbar(tokenizer.document_count)
        samples_seen = 0
        losses = []
        batch_loss = []
        for i, seq in enumerate(tokenizer.texts_to_sequences_generator(text_generator())):
            # get skipgram couples for one text in the dataset
            couples, labels = skipgrams(seq, vocab_size, window_size=4, negative_samples=1., sampling_table=sampling_table)
            if couples:
                # one gradient update per sentence (one sentence = a few 1000s of word couples)
                X = np.array(couples, dtype="int32")
                labels= np.array(labels, dtype="int32")

                loss = model.train_on_batch(X, labels)
                losses.append(loss)
                batch_loss.append(loss)
                if len(losses) % 10 == 0:
                    print ('\nBatch Loss: '+str(np.mean(batch_loss)))
                    progbar.update(i, values=[("loss", np.mean(losses))])
                    batch_loss = []
                samples_seen += len(labels)
        print('Samples seen:', samples_seen)
    print("Training completed!")
    json_string = model.to_json()
    open('sense_vectors_architecture.json', 'w').write(json_string)
    model.save_weights('sense_vectors_weights.h5')



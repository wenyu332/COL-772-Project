from keras import backend as K
from keras.models import Sequential
from keras.engine.topology import Layer
from keras.engine import InputSpec
from keras import initializations, activations
import theano
import theano.tensor as T
import theano.printing as printing
epsilon = 0.1

p = printing.Print('x')

def get_vector(curr_word, new_sense, W_g, W_s):
    cond = T.eq(new_sense, -1)
    return T.switch(cond, W_g[curr_word], W_s[curr_word, new_sense])

# update the sense of a word in the context vector
def change_context_vec(vect, new_sense, prev_sense, curr_word, W_g, W_s):
    return vect - get_vector(curr_word, prev_sense, W_g, W_s) + get_vector(curr_word, new_sense, W_g, W_s)

# updates the context vector with the best sense of the curr_word with (prev) sense curr_senses[i]
def l2C(curr_word, i, curr_senses, context_vector, W_g, W_s):
    # theano vector of size (num_senses,)
    scores_all_senses = T.dot(context_vector, W_s[curr_word].T)

    sorted_senses = T.argsort(scores_all_senses)
    score_best = scores_all_senses[sorted_senses[-1]]
    score_second_best = scores_all_senses[sorted_senses[-2]]

    prev_sense  = curr_senses[i]
    context_vector = T.switch(T.gt(score_best-score_second_best, epsilon),  change_context_vec(context_vector, sorted_senses[-1], prev_sense, curr_word, W_g, W_s), context_vector )
    new_senses = T.set_subtensor(curr_senses[i], sorted_senses[-1])
    return [new_senses, context_vector]

# Perform word sense disambiguation and learn better context vector
def disambiguate(context, context_length, W_g, W_s):
    context_vector = T.sum(W_g[context], axis = 0)
    # start with -1 with none of the words disambiguated
    start_sense = -1*T.ones_like(context)
    output_alg, updates = theano.scan(l2C, sequences = [context, T.arange(context_length)], outputs_info = [start_sense, context_vector], non_sequences = [W_g, W_s])
    disambiguated_senses = output_alg[0][-1]
    augmented_context_vector = output_alg[1][-1]
    return disambiguated_senses

def get_sense_vector(word, sense, inx, W_g, W_s):
    cond = inx <= -1
    # FOR NEGATIVE SAMPLES, -i INDICATES SENSE A NEATIVE SAMPLE OF SENSE i
    p = printing.Print('X')
    index = T.switch(cond, -inx -1, sense[inx])
    return get_vector(word, index, W_g, W_s)

class L2CEmbedding(Layer):
    # Creates multiple emdeddings per sense of the word.
    # Also keeps track of the senses of the context words and uses their embeddings.

    def __init__(self, num_senses, vocab_dim, vector_dim, input_dim, output_dim = 1, init = 'uniform', activation = 'sigmoid', **kwargs):
        self.input_dim = input_dim
        self.vector_dim = vector_dim 
        self.vocab_dim = vocab_dim
        self.init = initializations.get(init)
        self.activation = activations.get(activation)
        self.output_dim = output_dim
        self.num_senses = num_senses

        kwargs['input_dtype'] = 'int32'
        if self.input_dim:
            kwargs['input_shape'] = (self.input_dim, ) 
        super(L2CEmbedding, self).__init__(**kwargs)

    def build(self, input_shape):
        self.W_g = self.init((self.vocab_dim, self.vector_dim))
        self.W_s = self.init((self.vocab_dim, self.num_senses, self.vector_dim))
        self.trainable_weights = [self.W_g, self.W_s]

    def call(self, x, mask = None):
        # x is of dimension nb x (2*context_size + 3) where x[:,0] are the words, x[:,3:] is the context, x[:,1] is the context word and  x[:,2] is the INDEX of the context word in context     
        

        W_g = self.W_g
        W_s = self.W_s
        nb = x.shape[0]
        context_length = self.input_dim - 3
        actual_word_indx = (self.input_dim+3)/2 #same as context + 3
        right_senses,ignore_updates = theano.scan(disambiguate, sequences = x[:,3:], non_sequences = [context_length, W_g, W_s])
        words_sense_vector = W_s[x[:,0], right_senses[:,actual_word_indx]]
        a, ignore_updates = theano.scan(get_sense_vector, sequences = [x[:,0],right_senses,x[:,2]], non_sequences = [W_g, W_s])
        contexts_sense_vector = a
        sense_dot_prod = K.batch_dot(words_sense_vector, contexts_sense_vector, axes = 1)
        global_dot_prod = K.batch_dot(W_g[x[:,0]], W_g[x[:,1]], axes = 1)
        dot_prod = sense_dot_prod + global_dot_prod
        # return a[0]
        # return self.activation(K.log(K.sigmoid(dot_prod)))
        return self.activation(dot_prod)

    def get_output_shape_for(self, input_shape):
        assert input_shape and len(input_shape) == 2
        return (input_shape[0], 1)

    def get_config(self):
         return {"name":self.__class__.__name__,
                    "input_dim":self.input_dim,
                    "vector_dim":self.vector_dim,
                    "vocab_dim" :self.vocab_dim,
                    "init":self.init.__name__,
                    "activation":self.activation.__name__}

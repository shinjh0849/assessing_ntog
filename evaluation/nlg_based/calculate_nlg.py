import csv
import numpy as np
import os
import re
import nltk
import sys
import re
import bleu
import weighted_ngram_match
import syntax_match
import dataflow_match
import json
from rouge_score import rouge_scorer
from nltk.translate.meteor_score import meteor_score
from nltk.translate.bleu_score import sentence_bleu
from tree_sitter import Language, Parser



def get_toga_test():
    # targets_candidates = []
    preds_candidates = []
    
    with open('../../dataset/generated_asserts/toga.csv') as f:
        for line in csv.DictReader(f):
            preds_candidates.append(line)
    # with open(f'../toga/data/single_{data}/test.csv') as f:
    #     for line in csv.DictReader(f):
    #         targets_candidates.append(line)
    
    # assert len(preds_candidates) == len(targets_candidates)

    # group each candidates for preds
    preds_grouped = []
    cand = []
    idx = 1
    for i, row in enumerate(preds_candidates):
        cur_idx = int(row['test_num'])
        if idx != cur_idx:
            idx = cur_idx
            preds_grouped.append(cand)
            cand = []
            cand.append(row)
        else:
            cand.append(row)
            if i == len(preds_candidates) - 1:
                preds_grouped.append(cand)
    
    # get only one pred for each test
    preds = []
    targets = []
    for cands in preds_grouped:
        # check if has pred_lbl
        pred_row = []
        target_row = []
        one_pred = None
        for cand in cands:
            if cand['pred_lbl'] == '1':
                pred_row.append(cand)
            if cand['true_lbl'] == '1':
                target_row.append(cand)
        targets.append(target_row[0]['true_assertion']) 
        # if nothing is predicted
        if len(pred_row) == 0:
            # get lowest logit_0
            min_ = cands[0]['logit_0']
            one_pred = cands[0]
            for cand in cands:
                if cand['logit_0'] < min_:
                    min_ = cand['logit_0']
                    one_pred = cand
        # if there are more than 1 predictions
        elif len(pred_row) > 1:
            min_ = pred_row[0]['logit_0']
            one_pred = pred_row[0]
            for row in pred_row:
                if row['logit_0'] < min_:
                    min_ = row['logit_0']
                    one_pred = row
        elif len(pred_row) == 1:
            one_pred = pred_row[0]
            
        preds.append(one_pred['true_assertion'])
        
    return preds, targets


def calc_em_acc(preds, targets, toga):
    correct = 0
    if toga:
        total = toga
    else: 
        total = len(preds)
    for pred, target in zip(preds, targets):
        if pred.lower() == target.lower():
            correct += 1
    accuracy = correct / total

    return accuracy


def calc_codebleu(refs, hyps):
    lang = 'java'
    
    # preprocess inputs
    pre_references = [[x.strip() for x in refs]]
    hypothesis = [x.strip() for x in hyps]
    
    for i in range(len(pre_references)):
        assert len(hypothesis) == len(pre_references[i])

    references = []
    for i in range(len(hypothesis)):
        ref_for_instance = []
        for j in range(len(pre_references)):
            ref_for_instance.append(pre_references[j][i])
        references.append(ref_for_instance)
    assert len(references) == len(pre_references)*len(hypothesis)

    # calculate ngram match (BLEU)
    tokenized_hyps = [x.split() for x in hypothesis]
    tokenized_refs = [[x.split() for x in reference] for reference in references]
    
    ngram_match_score = bleu.corpus_bleu(tokenized_refs, tokenized_hyps)
    
    # calculate weighted ngram match
    keywords = [x.strip() for x in open('keywords/' + lang + '.txt', 'r', encoding='utf-8').readlines()]
    def make_weights(reference_tokens, key_word_list):
        return {token:1 if token in key_word_list else 0.2 \
                for token in reference_tokens}
    tokenized_refs_with_weights = [[[reference_tokens, make_weights(reference_tokens, keywords)]\
                for reference_tokens in reference] for reference in tokenized_refs]

    weighted_ngram_match_score = weighted_ngram_match.corpus_bleu(tokenized_refs_with_weights, tokenized_hyps)

    # calculate syntax match
    syntax_match_score = syntax_match.corpus_syntax_match(refs, hyps, lang)

    # calculate dataflow match
    dataflow_match_score = dataflow_match.corpus_dataflow_match(refs, hyps, lang)

    # print('ngram match: {0}, weighted ngram match: {1}, syntax_match: {2}, dataflow_match: {3}'.\
                        # format(ngram_match_score, weighted_ngram_match_score, syntax_match_score, dataflow_match_score))

    code_bleu_score = 0.25 * ngram_match_score\
                    + 0.25 * weighted_ngram_match_score\
                    + 0.25 * syntax_match_score\
                    + 0.25 * dataflow_match_score
    return code_bleu_score

def calc_bleu(preds, targets, toga):    
    # Calculate the BLEU score
    weights = [0.25] * 4  # weights for BLEU-4
    # bleu_score = nltk.translate.bleu_score.corpus_bleu(targets_tokens, preds_tokens, weights=weights)
   
    scores = []
    for pred, target in zip(preds, targets):
        each_bleu = nltk.translate.bleu_score.sentence_bleu([target], pred, weights=weights)
        scores.append(each_bleu)
    if toga:
        total_bleu = sum(scores) / toga
    else:
        total_bleu = sum(scores) / len(scores)
    return total_bleu



def calc_rouge_l(preds, targets, toga):
    if toga:
        total_len = toga
    else: total_len = len(targets)
    rouge_l = []
    for pred, target in zip(preds, targets):
        scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=True)
        rouge_scores = scorer.score(pred, target)
        rouge_l.append(rouge_scores['rougeL'].fmeasure)
    return round(sum(rouge_l) / total_len, 4)

def calc_meteor(preds, targets, toga):
    meteor_score_sentences_list = []
    for target, pred in zip(targets, preds):
        pred = pred.split()
        target = target.split()
        meteor_score_sentences_list.append(meteor_score([target], pred))
    if toga:
        diff = toga - len(preds)
        for _ in range(diff):
            meteor_score_sentences_list.append(0)
    meteor_score_res = np.mean(meteor_score_sentences_list)
    return meteor_score_res

def calc_metrics(baseline):
    if baseline == 'toga':
        is_toga = 29724
    else: is_toga = False
    
    preds = []
    targets = []
    if is_toga:
        preds, targets = get_toga_test()
    else:
        with open(f'../../dataset/generated_asserts/{baseline}.txt') as gen_f:
            for line in gen_f.readlines():
                preds.append(line.strip())
    
        path = '../../dataset/mining_atlas//Testing/assertLines_new.txt'
        with open(path) as test_f:
            for line in test_f.readlines(): 
                targets.append(line.strip())
    if baseline == 'atlas':
        new = []
        for tgt in targets:
            new.append(tgt.lower())
        targets = new
    assert len(targets) == len(preds)
    
    accuracy = calc_em_acc(preds, targets, is_toga)
    bleu = calc_bleu(preds, targets, is_toga)
    codeblue = calc_codebleu(preds, targets)
    rouge_l = calc_rouge_l(preds, targets, is_toga)
    meteor = calc_meteor(preds, targets, is_toga)
    
    print('======================================')
    print(baseline)
    print('Exact Match accuracy: {:.2f}'.format(accuracy * 100))
    print('BLEU-4 score: {:.2f}'.format(bleu * 100))
    print('CodeBLEU: {:.2f}'.format(codeblue * 100))
    print('ROUGE_L: {:.2f}'.format(rouge_l * 100))
    print('METEOR: {:.2f}'.format(meteor * 100))
    
    
def calc_metrics_project(baseline):
    toga_totals = {
        'cayenne': 772,
        'nifi': 911,
        'activemq-artemis': 707,
        'cloudstack': 726,
        'openmrs-core': 1184,
        'drill': 1138,
        'hadoop': 1112,
        'itext7': 1155,
        'cxf': 1133,
        'ignite': 899,
        'jackrabbit-oak': 1886,
        'james-project': 1509,
        'jena': 1512
    }
    
    for curdir, _, files in sorted(os.walk(f'../../dataset/injected_asserts/{baseline}')):
        if files:
            prj_name = curdir.split('/')[-1]
            
            try:
                with open(f'{curdir}/gen_new.txt') as f:
                    preds = f.readlines()
                with open(f'{curdir}/true_new.txt') as f:
                    targets = f.readlines()
            except FileNotFoundError as _:
                   continue
            if not len(targets): continue
            if not len(preds): continue 
            if len(targets) != len(preds): continue
            
            if baseline == 'toga':
                toga_total = toga_totals[prj_name]
            else: toga_total = None
            print('======================================')
            print(baseline, prj_name)
    
            accuracy = calc_em_acc(preds, targets, toga_total)
            bleu = calc_bleu(preds, targets, toga_total)
            codeblue = calc_codebleu(preds, targets)
            rouge_l = calc_rouge_l(preds, targets, toga_total)
            meteor = calc_meteor(preds, targets, toga_total)

            print('BLEU-4 score: {:.2f}'.format(bleu * 100))
            print('Exact Match accuracy: {:.2f}'.format(accuracy * 100))
            print('CodeBLEU: {:.2f}'.format(codeblue * 100))
            print('ROUGE_L: {:.2f}'.format(rouge_l * 100))
            print('METEOR: {:.2f}'.format(meteor * 100))



if sys.argv[1] == 'testset':
    for baseline in ['atlas', 'ir', 'toga', 'chatgpt']:
        calc_metrics(baseline)
elif sys.argv[1] == 'projects':
    for baseline in ['atlas', 'ir', 'toga', 'chatgpt']:
        calc_metrics_project(baseline)
else:
    print('wrong argument!')
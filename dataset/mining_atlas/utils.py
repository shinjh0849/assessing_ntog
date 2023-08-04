import os



# remove any project folders without assertion pairs
def rm_empty_files_n_filter(path):
    unique = []
    os.makedirs(f'{path}_filtered', exist_ok=True)
        
    for _, _, files in sorted(os.walk(f'{path}')):
        for file in sorted(files):
            if file.endswith('assertLines.txt'):
                continue
            prj_f = file.split('_testMethods')[0]
            fps = None
            try:
                if os.path.exists(f'my_atlas/{prj_f}_fp.txt'):
                    with open(f'my_atlas/{prj_f}_assertLines.txt', 'r') as ass_f:
                        assertions = ass_f.readlines()
                    with open(f'my_atlas/{prj_f}_testMethods.txt', 'r') as tms_f:
                        test_methods = tms_f.readlines()
                    with open(f'my_atlas/{prj_f}_fp.txt', 'r') as fp_f:
                        fps = fp_f.readlines()
                else:
                    with open(f'{path}/{prj_f}_assertLines.txt', 'r') as ass_f:
                        assertions = ass_f.readlines()
                    with open(f'{path}/{prj_f}_testMethods.txt', 'r') as tms_f:
                        test_methods = tms_f.readlines()
            except FileNotFoundError:
                continue
            if len(assertions) != len(test_methods):
                continue

            # remove empty files
            if len(assertions) == 0:
                os.remove(f'{path}/{prj_f}_assertLines.txt')
                os.remove(f'{path}/{prj_f}_testMethods.txt')
                print('removed', prj_f, '!!')

            filtered_x = []
            filtered_y = []
            filtered_fp = []
            if fps:
                for test_pre, assertion, fp in zip(test_methods, assertions, fps):
                    test_pre = test_pre.strip()
                    assertion = assertion.strip()
                    fp = fp.strip()
                    full = test_pre + ' ' + assertion
                    if len(full) < 1000 and full not in unique:
                        unique.append(full)
                        filtered_x.append(test_pre)
                        filtered_y.append(assertion)
                        filtered_fp.append(fp)
            else:
                for test_pre, assertion in zip(test_methods, assertions):
                    test_pre = test_pre.strip()
                    assertion = assertion.strip()
                    full = test_pre + ' ' + assertion
                    if len(full) < 1000 and full not in unique:
                        unique.append(full)
                        filtered_x.append(test_pre)
                        filtered_y.append(assertion)
            
            # if assertions less than 10: skip
            if len(filtered_x) <= 10:
                continue
            if filtered_x:
                if fps:
                    with open(f'{path}_filtered/{prj_f}_assertLines.txt', 'w') as f:
                        for y in filtered_y:
                            f.write(y + '\n')
                    with open(f'{path}_filtered/{prj_f}_testMethods.txt', 'w') as f:
                        for x in filtered_x:
                            f.write(x + '\n')
                    with open(f'{path}_filtered/{prj_f}_fp.txt', 'w') as f:
                        for fp in filtered_fp:
                            f.write(fp + '\n')
                else:
                    with open(f'{path}_filtered/{prj_f}_assertLines.txt', 'w') as f:
                        for y in filtered_y:
                            f.write(y + '\n')
                    with open(f'{path}_filtered/{prj_f}_testMethods.txt', 'w') as f:
                        for x in filtered_x:
                            f.write(x + '\n')
    print('filtering done')
    

# apply filertering then combine into one file
def apply_filter_n_combine():
    test_methods = []
    os.makedirs('my_atlas/comb', exist_ok=True)
    write_assert = open('my_atlas/comb/assertLines.txt', 'w')
    write_testpre = open('my_atlas/comb/testMethods.txt', 'w')
    for curdir, _, files in sorted(os.walk('my_atlas_filtered/')):
        for file in sorted(files):
            if file.endswith('assertLines.txt'):
                with open(f'{curdir}/{file}', 'r') as f:
                    assertions = f.readlines()
            else:
                print(f'{curdir}/{file}')
                with open(f'{curdir}/{file}', 'r') as f:
                    test_pres = f.readlines()
                assert len(assertions) == len(test_pres)
                if len(assertions) == 0:
                    continue

                for assertion, test_pre in zip(assertions, test_pres):
                    test_method = test_pre + assertion
                    if len(test_method) > 1000:
                        continue
                    if test_method not in test_methods:
                        test_methods.append(test_method)
                        write_assert.write(assertion)
                        write_testpre.write(test_pre)
    write_testpre.close()
    write_assert.close()
    print(len(test_methods))

# split train eval and test
def single_split(path='my_atlas'):
    with open('my_atlas/comb/assertLines.txt') as f:
        t = f.readlines()
    total_num = len(t)
    os.makedirs(f'{path}/Eval', exist_ok=True)
    os.makedirs(f'{path}/Training', exist_ok=True)
    os.makedirs(f'{path}/Testing', exist_ok=True)
    train_assert = open(f'{path}/Training/assertLines.txt', 'w')
    train_testpre = open(f'{path}/Training/testMethods.txt', 'w')
    test_assert = open(f'{path}/Testing/assertLines.txt', 'w')
    test_testpre = open(f'{path}/Testing/testMethods.txt', 'w')
    eval_assert = open(f'{path}/Eval/assertLines.txt', 'w')
    eval_testpre = open(f'{path}/Eval/testMethods.txt', 'w')
    test_cnt = 0
    eval_cnt = 0
    train_cnt = 0
    test_list = ['apache@activemq-artemis','apache@cloudstack','apache@cayenne',
                 'bonitasoft@bonita-engine','apache@brooklyn-server','apache@ignite',
                 'apache@jclouds','apache@nifi','ifnul@ums-backend','apache@flink',
                 'apache@kafka','apache@hadoop','apache@cxf','apache@drill',
                 'itext@itext7','openmrs@openmrs-core','apache@beam','cdk@cdk',
                 'apache@james-project','apache@jena','OpenGamma@Strata',
                 'eclipse@eclipse-collections','apache@jackrabbit-oak','apache@camel']
    
    for curdir, _, files in os.walk(f'{path}/comb'):
        for file in files:
            if file.endswith('assertLines.txt'):
                continue
            prj = file.split('_testMethods.txt')[0]

            with open(f'{path}/comb/{prj}_assertLines.txt') as f:
                assertions = f.readlines()
            with open(f'{path}/comb/{prj}_testMethods.txt') as f:
                test_pres = f.readlines()

            if prj in test_list:
                test_testpre.writelines(test_pres)
                test_assert.writelines(assertions)
                test_cnt += len(assertions)
                continue

            if eval_cnt <= total_num/10:
                eval_testpre.writelines(test_pres)
                eval_assert.writelines(assertions)
                eval_cnt += len(assertions)
            else:
                train_assert.writelines(assertions)
                train_testpre.writelines(test_pres)
                train_cnt += len(assertions)
    print('train', train_cnt, 'eval', eval_cnt, 'test', test_cnt)


# apply filtering then split into train test and eval
def apply_filter_n_split(total_num, in_path):
    test_methods = []
    os.makedirs(f'{in_path}/Training', exist_ok=True)
    os.makedirs(f'{in_path}/Testing', exist_ok=True)
    os.makedirs(f'{in_path}/Eval', exist_ok=True)
    train_assert = open(f'{in_path}/Training/assertLines.txt', 'w')
    train_testpre = open(f'{in_path}/Training/testMethods.txt', 'w')
    test_assert = open(f'{in_path}/Testing/assertLines.txt', 'w')
    test_testpre = open(f'{in_path}/Testing/testMethods.txt', 'w')
    eval_assert = open(f'{in_path}/Eval/assertLines.txt', 'w')
    eval_testpre = open(f'{in_path}/Eval/testMethods.txt', 'w')
    test_cnt = 0
    eval_cnt = 0
    train_cnt = 0
    for curdir, _, files in sorted(os.walk(f'{in_path}/raw')):
        for file in sorted(files):
            if file.endswith('assertLines.txt'):
                with open(f'{curdir}/{file}', 'r') as f:
                    assertions = f.readlines()
            else:
                print(f'{curdir}/{file}')
                with open(f'{curdir}/{file}', 'r') as f:
                    test_pres = f.readlines()
                assert len(assertions) == len(test_pres)
                if len(assertions) == 0:
                    continue

                cnt = 0
                split = ''
                for assertion, test_pre in zip(assertions, test_pres):
                    test_method = test_pre + assertion
                    if len(test_method.split()) > 1000:
                        continue
                    cnt += 1
                    if test_method not in test_methods:
                        test_methods.append(test_method)
                        if eval_cnt <= total_num/10:
                            eval_assert.write(assertion)
                            eval_testpre.write(test_pre)
                            split = 'eval'
                        elif test_cnt <= total_num/10:
                            test_assert.write(assertion)
                            test_testpre.write(test_pre)
                            split = 'test'
                        else:
                            train_assert.write(assertion)
                            train_testpre.write(test_pre)
                if split == 'eval':
                    eval_cnt += cnt
                elif split == 'test':
                    test_cnt += cnt
                else:
                    train_cnt += cnt

    test_assert.close()
    test_testpre.close()
    eval_assert.close()
    eval_testpre.close()
    train_assert.close()
    train_testpre.close()
    print('train:', train_cnt, 'eval:', eval_cnt, 'test:', test_cnt)


# combine each project files in to one files
def combine_dir_to_one_file(path):
    write_assertion = open(f'{path}/Testing/assertLines.txt', 'w')
    write_test = open(f'{path}/Testing/testMethods.txt', 'w')
    write_fps = open(f'{path}/Testing/fps.txt', 'w')


    for curdir, _, files in os.walk(f'output/{path}/raw'):
        for file in files:
            if file.endswith('assertLines.txt') or file.endswith('fp.txt'):
                continue
            prj = file.split('_testMethods.txt')[0]
            
            with open(f'{path}/raw/{prj}_assertLines.txt') as f:
                assertions = f.readlines()
            with open(f'{path}/raw/{prj}_testMethods.txt') as f:
                test_pres = f.readlines()
            with open(f'{path}/raw/{prj}_fp.txt') as f:
                fps = f.readlines()

            write_assertion.writelines(assertions)
            write_test.writelines(test_pres)
            write_fps.writelines(fps)

    write_assertion.close()
    write_test.close()
    write_fps.close()
    
# process assertions
def preprocess_assertions_all(baseline):        
    with open(f'pit/generated/all/{baseline}.txt') as f:
        generated = f.readlines()
    with open('my_single_filtered/single_all/Testing/assertLines.txt') as f:
        trues = f.readlines()
    new_gen = []
    new_true = []
    for true, gen in zip(trues, generated):
        gen = gen.strip()
        true = true.strip()
        
        if gen.startswith('AssertPlaceHolder : '):
            gen = gen.replace('AssertPlaceHolder : ', '')
        if gen.startswith('`'):
            gen = gen.replace('`', '')
            gen = gen.strip()
        if gen.startswith('Assert . '):
            gen = gen.replace('Assert . ', '')
        if gen.startswith('Assertions . '):
            gen = gen.replace('Assertions . ', '')
        if gen.startswith('. '):
            gen = gen[2:]
        
        if true.startswith('Assert . '):
            true = true.replace('Assert . ', '')
        if true.startswith('Assertions . '):
            true = true.replace('Assertions . ', '')
        if true.startswith('. '):
            true = true[2:]
            
        new_true.append(true)
        new_gen.append(gen)
    with open(f'pit/generated/all/{baseline}_new.txt', 'w') as f:
        for line in new_gen:
            f.write(line + '\n')
    with open('my_single_filtered/single_all/Testing/assertLines_new.txt', 'w') as f:
        for line in new_true:
            f.write(line + '\n')

# proces the generated assertions 
def preprocess_assertions(baseline):
    for curdir, _, files in sorted(os.walk(f'pit/injected_asserts/{baseline}')):
        if files:
            prj_name = curdir.split('/')[-1]
            
            with open(f'{curdir}/gen_asserts.txt') as f:
                gen_asserts = f.readlines()
            with open(f'{curdir}/true_asserts.txt') as f:
                true_asserts = f.readlines()
               
            if not len(gen_asserts): continue
            if not len(true_asserts): continue 
            if len(true_asserts) != len(true_asserts): continue
    
            print('======================================')
            print(baseline, prj_name)
            
            new_gen = []
            new_true = []
            for gen, true in zip(gen_asserts, true_asserts):
                gen = gen.strip()
                true = true.strip()
                if gen.startswith('Assert . '):
                    gen = gen.replace('Assert . ', '')
                if gen.startswith('Assertions . '):
                    gen = gen.replace('Assertions . ', '')
                if true.startswith('Assert . '):
                    true = true.replace('Assert . ', '')
                if true.startswith('Assertions . '):
                    true = true.replace('Assertions . ', '')
                new_gen.append(gen)
                new_true.append(true)
            
            with open(f'{curdir}/gen_new.txt', 'w') as f:
                for line in new_gen:
                    f.write(line + '\n')
            with open(f'{curdir}/true_new.txt', 'w') as f:
                for line in new_true:
                    f.write(line + '\n')
                    

rm_empty_files_n_filter('my_atlas')
apply_filter_n_combine()
single_split()
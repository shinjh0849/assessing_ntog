from bs4 import BeautifulSoup
import csv
import os
import subprocess
from tree_sitter import Language, Parser
import sys

# prepare tree-sitter parser
Language.build_library(
    '../build/my-java.so',
    ['../build/tree-sitter-java']
)
JAVA_LANGUAGE = Language('../build/my-java.so', 'java')
JAVA_PATTERNS = {
    'CLASS_DEC': '''
    (class_declaration
        (modifiers) @mod 
        name: (identifier) @name
        body: (class_body) @body
    )''',
    'METHOD_NAME': '''
    (method_declaration
        name: (identifier)) @definition.method
     ''',
    'MARKER_ANNOTATION': '''
    (method_declaration
        (modifiers
            (marker_annotation name: (identifier) @marker_annotation)
        )
        name: (identifier) @name
    )''',
    'ANNOTATION': '''
    (method_declaration
        (modifiers
            (annotation name: (identifier) @annotation)
        )
        name: (identifier) @name
    )''',
    'METHOD_INV': '''
    (method_invocation) @name
    '''
}

parser = Parser()
parser.set_language(JAVA_LANGUAGE)

target_prj_list = [
    'apache@activemq-artemis',
    'apache@cloudstack',
    'apache@cayenne',
    'apache@ignite',
    'apache@nifi',
    'apache@hadoop',
    'apache@cxf',
    'apache@drill',
    'itext@itext7',
    'openmrs@openmrs-core',
    'apache@james-project',
    'apache@jena', 
    'apache@jackrabbit-oak'
]

# getting the blob from the parse tree
def get_blob(code, node):
    return code[node.start_byte:node.end_byte]


def get_toga_test():
    toga = []
    with open('generated/all/toga.csv') as f:
        for line in csv.DictReader(f):
            toga.append(line)

    # group each test candidates
    toga_each_test = []
    cand = []
    idx = 1
    for row in toga:
        cur_idx = int(row['test_num'])
        if idx != cur_idx:
            idx = cur_idx
            toga_each_test.append(cand)
            cand = []
            cand.append(row)
        else:
            cand.append(row)
    
    test_asserts = []
    # get only one test
    for cands in toga_each_test:
        test_row = []
        for cand in cands:
            if cand['true_lbl'] == '1':
                test_row.append(cand)
        test_asserts.append(test_row[0]['true_assertion'])
    
    # get only one pred for each test
    toga_one_preds = []
    for cands in toga_each_test:
        # check if has pred_lbl
        pred_row = []
        one_pred = None
        for cand in cands:
            # if there is pred get it
            if cand['pred_lbl'] == '1':
                pred_row.append(cand)
        # if nothing is predicted
        if not pred_row:
            # get lowest logit_0
            min_ = cands[0]['logit_0']
            one_pred = cands[0]
            for cand in cands:
                if cand['logit_0'] < min_:
                    min_ = cand['logit_0']
                    one_pred = cand
        # if there is more than one pred
        elif len(pred_row) > 1:
            min_ = pred_row[0]['logit_0']
            one_pred = pred_row[0]
            for row in pred_row:
                if row['logit_0'] < min_:
                    min_ = row['logit_0']
                    one_pred = row
        # if there is only one pred get it
        elif len(pred_row) == 1:
            one_pred = pred_row[0]

        toga_one_preds.append(one_pred)

    gen_asserts = []
    gen_test_names = []
    gen_files = []
    for pred in toga_one_preds:
        gen_asserts.append(pred['true_assertion'])
        gen_test_names.append(pred['test'].split()[0])
        gen_files.append('/'.join(pred['paths'].split('/')[3:]))

    return gen_asserts, gen_test_names, gen_files, test_asserts


def clone_projects(baseline):
    os.makedirs(f'projects/{baseline}', exist_ok=True)
    prj_list = target_prj_list
    for prj in prj_list:
        print('Cloning project:', prj)
        prj_name = prj.replace('@', '/')
        try:
            p = subprocess.Popen(
                f'cd projects/{baseline}/ && git clone https://github.com/{prj_name}.git',
                stdout=subprocess.PIPE,
                shell=True)
            p.communicate()
        except OSError:
            print(f'{prj_name} clone error!')
            continue


def rm_orig_tests(code):
    has_test = False
    tree = parser.parse(bytes(code, 'utf8'))
    root_node = tree.root_node
    mark_ann_query = JAVA_LANGUAGE.query(JAVA_PATTERNS['MARKER_ANNOTATION'])
    mark_ann_captures = mark_ann_query.captures(root_node)
    ann_query = JAVA_LANGUAGE.query(JAVA_PATTERNS['ANNOTATION'])
    ann_captures = ann_query.captures(root_node)

    # get original test, with @Test annotations
    test_annotated = []
    for cp in mark_ann_captures:
        if get_blob(code, cp[0]) == 'Test':
            test_annotated.append(cp[0].parent.parent.parent)
    for cp in ann_captures:
        if get_blob(code, cp[0]) == 'Test':
            test_annotated.append(cp[0].parent.parent.parent)
    copy = code

    if test_annotated:
        has_test = True
        for tc in test_annotated:
            tc_code = get_blob(code, tc)
            copy = copy.replace(tc_code, '')

    return has_test, copy


# parse the original file and remove method with '@Test'
def replace_assertion(code, gen_asserts, gen_test_names, true_tests, cur_fp):
    is_tc_removed = False
    log_path = 'logs/assert_inject_error'
    os.makedirs(log_path, exist_ok=True)
    exe_fp = cur_fp.replace('SUBPROJECT', 'EXECUTION')
    tree = parser.parse(bytes(code, 'utf8'))
    root_node = tree.root_node
    class_query = JAVA_LANGUAGE.query(JAVA_PATTERNS['CLASS_DEC'])
    class_captures = class_query.captures(root_node)
    mark_ann_query = JAVA_LANGUAGE.query(JAVA_PATTERNS['MARKER_ANNOTATION'])
    mark_ann_captures = mark_ann_query.captures(root_node)
    ann_query = JAVA_LANGUAGE.query(JAVA_PATTERNS['ANNOTATION'])
    ann_captures = ann_query.captures(root_node)
    inj_asserts = []
    inj_true = []
    inj_info = []
    
    # get class name
    class_name = ''
    for point, notation in class_captures:
        if notation == 'name':
            class_name = get_blob(code, point)
    if not class_name:
        print('fail to parse class name')
        print(code)
        return False, 0, 0, code, code, code, inj_asserts, inj_true, inj_info
    # is_tc_removed, se_cnt, ee_cnt, all_injected, rem_inj, subproject_rm, inj_asserts, inj_true, inj_info
    
    # get original test, with @Test annotations
    test_annotated = []
    test_names = []
    method = ''
    is_test = False
    for cp in mark_ann_captures:
        if cp[1] == 'marker_annotation' and get_blob(code, cp[0]) == 'Test':
            method = cp[0].parent.parent.parent
            is_test = True
        elif cp[1] == 'name' and is_test:
            test_annotated.append(method)
            test_names.append(get_blob(code, cp[0]))
            is_test = False
    for cp in ann_captures:
        if cp[1] == 'annotation' and get_blob(code, cp[0]) == 'Test':
            method = cp[0].parent.parent.parent
            is_test = True
        elif cp[1] == 'name' and is_test:
            test_annotated.append(method)
            test_names.append(get_blob(code, cp[0]))
            is_test = False

    # replacing assertions
    subproject_rm = all_inj = copy = code
    copy_lines = copy.splitlines()
    all_lines = all_inj.splitlines()
    offset = 0
    all_offset = 0
    # for each @test annotated methods
    for test_ann, test_name in zip(test_annotated, test_names):
        test_flag = False
        all_idx = test_ann.start_point[0] - all_offset 
        test_start_idx = test_ann.start_point[0] - offset
        assert_idx = test_start_idx
        test = get_blob(code, test_ann)
        a_tree = parser.parse(bytes(test, 'utf8'))
        a_root_node = a_tree.root_node
        # check the generated test names
        for gen_ass, gen_name, true_test in zip(gen_asserts, gen_test_names, true_tests):
            # if test name matches, replace the assertion with generated
            if gen_name == test_name:
                test_flag = True
                invoc_query = JAVA_LANGUAGE.query(JAVA_PATTERNS['METHOD_INV'])
                invoc_captures = invoc_query.captures(a_root_node)
                
                # find assert invocations
                for point, name in invoc_captures:
                    if 'assert' in get_blob(test, point).lower():
                        assert_idx += point.start_point[0]
                        all_idx += point.start_point[0]
                        break
                    
                # save to file before action (injection, se check, ee check)
                with open(exe_fp.replace('.java', '.SAVED'), 'w') as f:
                    f.write(copy)    
                
                # inject assertion at the correct location
                copy_lines[assert_idx] = gen_ass + ' ;'
                copy = '\n'.join(copy_lines)
                all_lines[all_idx] = gen_ass + ' ;'
                all_inj = '\n'.join(all_lines)
                inj_asserts.append(gen_ass)
                inj_true.append(true_test)
                inj_info.append({'file_path': cur_fp, 'test_name': test_name})
                
                # check if injection result in syntax error
                t_tree = parser.parse(bytes(copy, 'utf8'))
                t_root = t_tree.root_node
                # if syntax error, remove the test method and save log
                if 'error' in t_root.sexp().lower():
                    is_tc_removed = True
                    subproject_rm = subproject_rm.replace(test, '')
                    copy = copy.replace(test, '')
                    copy_lines = copy.splitlines()
                    offset += len(test.splitlines()) - 1
                    all_offset += len(test.splitlines()) - 1
                    inj_asserts.pop()
                    inj_true.pop()
                    inj_info.pop()
                    
                # check execution error
                # save the change to the file
                with open(exe_fp, 'w') as f:
                    f.write(copy)
                # run pit to check execution error
                cd_path = exe_fp.split('src')[-2]
                p = subprocess.Popen(
                    f'cd {cd_path} && mvn clean && mvn test -Dtest={class_name}#{test_name}',
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    shell=True)
                std_out, _ = p.communicate()
                std_out = std_out.decode()
                
                # check if injection result in execution failure 
                if 'BUILD FAILURE' in std_out:
                    # remove the test method
                    is_tc_removed = True
                    subproject_rm = subproject_rm.replace(test, '')
                    copy = copy.replace(test, '')
                    copy_lines = copy.splitlines()
                    offset += len(test.splitlines()) - 1
                    all_offset += len(test.splitlines()) - 1
                    
                    # check if execution error
                    # save to file the change
                    with open(exe_fp, 'w') as f:
                        f.write(copy)
                        offset_sav = offset
                    # run pit to check ee
                    cd_path = exe_fp.split('src')[-2]
                    p = subprocess.Popen(
                        f'cd {cd_path} && mvn clean && mvn test -Dtest={class_name}#{test_name}',
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=True)
                    std_out, _ = p.communicate()
                    std_out = std_out.decode()
                    
                    # if remove result in failure
                    if 'BUILD FAILURE' in std_out:
                        # bring back the original before any actions
                        with open(exe_fp.replace('.java', '.SAVED'), 'r') as f:
                            save_back = f.read()
                        with open(exe_fp, 'w') as f:
                            f.write(save_back)
                        subproject_rm = save_back
                        copy = save_back
                        copy_lines = copy.splitlines()
                        offset = offset_sav
                        
        # if there is no assertion name match, remove the test case
        if not test_flag:
            # save to file before action (injection, se check)
            with open(exe_fp.replace('.java', '.SAVED'), 'w') as f:
                f.write(copy)
                offset_sav = offset
            
            # remove test case
            is_tc_removed = True
            subproject_rm = subproject_rm.replace(test, '')
            copy = copy.replace(test, '')
            copy_lines = copy.splitlines()
            offset += len(test.splitlines()) - 1
            all_offset += len(test.splitlines()) - 1
            all_inj = all_inj.replace(test, '')
            all_lines = all_inj.splitlines()
                
            # check if execution error
            # save to file the change
            with open(exe_fp, 'w') as f:
                f.write(copy)
            # run pit to check ee
            cd_path = exe_fp.split('src')[-2]
            p = subprocess.Popen(
                f'cd {cd_path} && mvn clean && mvn test -Dtest={class_name}#{test_name}',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True)
            std_out, _ = p.communicate()
            std_out = std_out.decode()
            
            # if it resulted in build failure, 
            if 'BUILD FAILURE' in std_out:
                # bring back the saved
                with open(exe_fp.replace('.java', '.SAVED'), 'r') as f:
                    save_back = f.read()
                with open(exe_fp, 'w') as f:
                    f.write(save_back)
                subproject_rm = save_back
                copy = save_back
                copy_lines = copy.splitlines()
                offset = offset_sav
    rem_inj = '\n'.join(copy_lines)
    all_injected = '\n'.join(all_lines)
    return is_tc_removed, all_injected, rem_inj, subproject_rm, inj_asserts, inj_true, inj_info


def replace_existing_tests(baseline):
    prj_list = target_prj_list
    os.makedirs(f'projects/{baseline}/INJECTED', exist_ok=True)
    os.makedirs(f'projects/{baseline}/INJECTED_with_err', exist_ok=True)
    os.makedirs(f'projects/{baseline}/SUBPROJECT_rm', exist_ok=True)
    for prj in prj_list:
        test_asserts = []
        test_names = []
        test_files = []
        true_tests = []
        prj_name = prj.split('@')[1]
        os.makedirs(f'injected_asserts/{baseline}/{prj_name}', exist_ok=True)
        inj_asserts_f = open(f'injected_asserts/{baseline}/{prj_name}/gen_asserts.txt', 'w')
        inj_true_f = open(f'injected_asserts/{baseline}/{prj_name}/true_asserts.txt', 'w')
        inj_info_f = open(f'injected_asserts/{baseline}/{prj_name}/asserts_info.txt', 'w')
        if baseline == 'toga':
            test_asserts, test_names, test_files, true_tests = get_toga_test()
        else:
            with open(f'generated/all/{baseline}.txt', 'r') as f:
                test_asserts = [line.strip() for line in f.readlines()]
            with open('../output/my_single_filtered/single_all/Testing/testMethods.txt', 'r') as f:
                test_names = [test.split()[0] for test in f.readlines()]
            with open('../output/my_single_filtered/single_all/Testing/fps.txt', 'r') as f:
                test_files = ['/'.join(fp.split('/')[3:]).strip()
                              for fp in f.readlines()]
            with open('../output/my_single_filtered/single_all/Testing/assertLines.txt', 'r') as f:
                true_tests = [line.strip() for line in f.readlines()]
                
        assert len(test_asserts) == len(test_names) == len(test_files) == len(true_tests)
        
        # iterate all java files in the subproject repos
        for curdir, _, files in sorted(os.walk(f'projects/{baseline}/SUBPROJECT/{prj_name}')):
            for file in sorted(files):
                cur_file_path = os.path.join(curdir, file)
                project_file_path = '/'.join(cur_file_path.split('/')[3:])
                # print(project_file_path)
                inj_dir = curdir.replace('SUBPROJECT', 'INJECTED')
                inj_with_err = curdir.replace('SUBPROJECT', 'INJECTED_with_err')
                sub_rm = curdir.replace('SUBPROJECT', 'SUBPROJECT_rm')
                os.makedirs(inj_dir, exist_ok=True)
                os.makedirs(sub_rm, exist_ok=True)
                os.makedirs(inj_with_err, exist_ok=True)
                
                # for all java files
                if file.endswith('.java'):
                    with open(cur_file_path) as f:
                        code = f.read()
                    names = []
                    asserts = []
                    tests = []
                    # check if we have generated assertions for the file
                    if project_file_path in test_files:
                        for name, assrt, fp, test in zip(test_names, test_asserts, test_files, true_tests):
                            if fp == project_file_path:
                                names.append(name)
                                asserts.append(assrt)
                                tests.append(test)
                        is_test_rm, all_injected, rm_injected, subproject_with_rm, inj_asserts, inj_true, inj_info = replace_assertion(code, asserts, names, tests, cur_file_path)
                        # write injected asserts and ground truth in separate files
                        for i_a in inj_asserts:
                            inj_asserts_f.write(i_a + '\n')
                        for i_t in inj_true:
                            inj_true_f.write(i_t + '\n')
                        for i_i in inj_info:
                            inj_info_f.write(str(i_i) + '\n')
                        # if tests are removed == there are errors
                        # -> copy all injected to w/ errors and removed to w/o errors
                        if is_test_rm:
                            with open(f'{inj_with_err}/{file}', 'w') as f:
                                f.write(all_injected)
                            with open(f'{inj_dir}/{file}', 'w') as f:
                                f.write(rm_injected)
                            with open(f'{sub_rm}/{file}', 'w') as f:
                                f.write(subproject_with_rm)
                        # if not removed == no errors -> save all_injected code to both w/ & w/o errors
                        else:
                            with open(f'{inj_with_err}/{file}', 'w') as f:
                                f.write(all_injected)
                            with open(f'{inj_dir}/{file}', 'w') as f:
                                f.write(all_injected)
                            with open(f'{sub_rm}/{file}', 'w') as f:
                                f.write(code)
                    # for all other java files, just remove all @Test
                    else:
                        has_test, code = rm_orig_tests(code)
                        # if java file has tcs that are not in test set remove and save/copy
                        if has_test:
                            with open(f'{inj_with_err}/{file}', 'w') as f:
                                f.write(code)
                            with open(f'{inj_dir}/{file}', 'w') as f:
                                f.write(code)
                            with open(f'{sub_rm}/{file}', 'w') as f:
                                f.write(code)
                        # if java doesn't have tcs plain copy
                        else:
                            cp_command = f'cp {curdir}/{file} {inj_dir}/{file}'
                            subprocess.run(['sudo', 'bash', '-c', cp_command])
                            cp_command = f'cp {curdir}/{file} {sub_rm}/{file}'
                            subprocess.run(['sudo', 'bash', '-c', cp_command])
                            cp_command = f'cp {curdir}/{file} {inj_with_err}/{file}'
                            subprocess.run(['sudo', 'bash', '-c', cp_command])
                # copy other non java files that are not class
                elif not file.endswith('.class'):
                    cp_command = f'cp {curdir}/{file} {inj_dir}/{file}'
                    subprocess.run(['sudo', 'bash', '-c', cp_command])
                    cp_command = f'cp {curdir}/{file} {sub_rm}/{file}'
                    subprocess.run(['sudo', 'bash', '-c', cp_command])
                    cp_command = f'cp {curdir}/{file} {inj_with_err}/{file}'
                    subprocess.run(['sudo', 'bash', '-c', cp_command])
        inj_asserts_f.close()
        inj_true_f.close()            
        
                  
def make_sub_project(out_dir):
    # read filepath name of test set and remove dups
    with open('../../dataset/mining_atlas/Testing/fps.txt', 'r') as f:
        fps = ['/'.join(fp.split('/')[3:]).strip() for fp in f.readlines()]
    fps = sorted(list(set(fps)))
        
    prj_list = target_prj_list
    # iterate the project lists
    for prj in prj_list:
        prj_name = prj.split('@')[1]
        
        # walk all files in the project
        for curdir, _, files in sorted(os.walk(f'projects/CLONED/{prj_name}')):
            path = curdir.replace('projects/CLONED/', '')
            write_dir = curdir.replace('CLONED', out_dir)
            os.makedirs(write_dir, exist_ok=True)
            print(curdir)
            # check all files that has 'test' in the directory name
            if 'test' in curdir.lower() and 'src/main' not in curdir.lower():
                for file in files:
                    # check all the java files (our target)
                    if file.endswith('.java'):
                        cur_fp = f'{path}/{file}'
                        # only if it is our target test file COPY
                        if cur_fp in fps:
                            cp_command = f'cp {curdir}/{file} {write_dir}/{file}'
                            subprocess.run(['sudo', 'bash', '-c', cp_command])
                        with open(f'{curdir}/{file}') as f:
                            code = f.read()
                        # if the file does not have any assertions
                        if 'assert' not in code.lower():
                            cp_command = f'cp {curdir}/{file} {write_dir}/{file}'
                            subprocess.run(['sudo', 'bash', '-c', cp_command])
                    # all non java files in test dir, COPY
                    else:
                        cp_command = f'cp {curdir}/{file} {write_dir}/{file}'
                        subprocess.run(['sudo', 'bash', '-c', cp_command])
            # all files that are NOT in test dir, COPY
            else:
                for file in files:
                    cp_command = f'cp {curdir}/{file} {write_dir}/{file}'
                    subprocess.run(['sudo', 'bash', '-c', cp_command])


def copy_missing_file(missing, prj, in_dir):
    missing = missing.split('/')
    file_name = missing[-1]
    file_dir = '/'.join(missing[:-1])
    for curdir, _, files in sorted(os.walk(f'projects/CLONED/{prj}')):
        if curdir == file_dir and file_name in files:
            write_path = curdir.replace('CLONED', in_dir)
            cp_command = f'cp {curdir}/{file_name} {write_path}/{file_name}'
            subprocess.run(['sudo', 'bash', '-c', cp_command])


def copy_locations(missing, prj, in_dir):
    location, symbol = missing
    missing_path = location.replace('.', '/')
    for curdir, _, files in sorted(os.walk(f'projects/CLONED/{prj}')):
        if missing_path in curdir:
            write_path = curdir.replace('CLONED', in_dir)
            os.makedirs(write_path, exist_ok=True)
            if symbol == '*':
                for f in files:
                    cp_command = f'cp {curdir}/{f} {write_path}/{f}'
                    subprocess.run(['sudo', 'bash', '-c', cp_command])
            elif symbol + '.java' in files:
                file_n = symbol + '.java'
                cp_command = f'cp {curdir}/{file_n} {write_path}/{file_n}'
                subprocess.run(['sudo', 'bash', '-c', cp_command])


def check_sub_project_sub(in_dir):
    sub_project_build_fail = True
    cmd = 'mvn clean test'
    prj_list = target_prj_list    
        
    for prj in prj_list:
        prj_name = prj.split('@')[-1]
        print(f'starting {prj_name} with {cmd}')
        for curdir, _, files in sorted(os.walk(f'projects/{in_dir}/{prj_name}')):
            if 'pom.xml' in files and len(curdir.split('/')) > 3:
                while sub_project_build_fail:
                    print('pom.xml found in', curdir)
                    try:
                        p = subprocess.Popen(
                            f'cd {curdir} && {cmd}',
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            shell=True)
                        std_out, _ = p.communicate()
                    except Exception as e:
                        print(str(e))
                    std_out = std_out.decode()

                    sub_project_build_fail = handle_errors(in_dir, std_out, prj_name)

            
                
def handle_errors(in_dir, std_out, prj_name):
    print(std_out)
    # if build fail, fix the problem
    if 'BUILD FAILURE' in std_out:
        sub_project_build_fail = True
        # for each line of the log, identify and fix the bug
        for i, line in enumerate(std_out.splitlines()):
            err_splt = line.split()
            # handle line that startswith timestamp
            if len(err_splt) > 1 and err_splt[1] == '[ERROR]':
                line = ' '.join(err_splt[1:]).strip()
            # if cannot find symbol
            if line.startswith('[ERROR] ') and 'cannot find symbol' in line:
                # get the locations
                # if there is location in 2nd line
                if 'location: 'in std_out.splitlines()[i+2]:
                    location = std_out.splitlines()[i+2]
                    # if location is a package
                    if 'location: package ' in location:
                        location = location.split('location: package ')[-1]
                    # if search within the code
                    elif '.java:[' in line.split()[1]:
                        location = line.split()[1]
                        location = location.split(':')
                        fp = location[0]
                        fp_dir = fp.replace(in_dir, 'CLONED')
                        fp_dir = '/'.join(fp_dir.split('/')[:-1])
                        line_no = int(location[1].replace('[','').split(',')[0])
                        symbol = std_out.splitlines()[i+1]
                        symbol = symbol.split()[-1]
                        with open(fp, 'r') as f:
                            code = f.readlines()
                        # if loc is an import
                        if code[line_no - 1].startswith('import'): 
                            location = code[line_no - 1].split()[-1]
                            loc = location.split('.')
                            location = '.'.join(loc[:-1])
                            symbol = loc[-1].replace(';', '')
                            copy_locations((location, symbol), prj_name, in_dir)
                            continue
                        # if the symbol is called when extending a super
                        elif 'extends' in code[line_no - 1]:
                            loc = code[line_no - 1].split('extends ')[-1]
                            loc = loc.replace('{', '').strip()
                            loc = loc.split('.')
                            location = '.'.join(loc[:-1])
                            symbol = loc[-1]
                            copy_locations((location, symbol), prj_name, in_dir)
                        # if the symbol is a method of super
                        elif code[line_no - 1].strip == f'super.{symbol};':
                            for code_line in code:
                                if 'extends' in code_line:
                                    symbol = code_line.split('extends ')[-1]
                                    symbol = symbol.replace('{', '').strip()
                                    break
                            for code_line in code:
                                if 'import' in code_line and symbol in code_line:
                                    location = code_line.replace('import', '').replace(';', '').strip()
                                    break
                            copy_locations((location, symbol), prj_name, in_dir)
                        # elif there is symbol in the current package
                        elif symbol + '.java' in os.listdir(fp_dir):
                            fp_dir = fp_dir.split('CLONED/')[-1]
                            copy_locations((fp_dir, symbol), prj_name, in_dir)
                            continue
                        # else, search wildcard imports
                        else:
                            for c in code:
                                c = c.strip()
                                if c.startswith('import') and c.endswith('.*;') and prj_name in c:
                                    loc = c.replace('import', '').replace(';', '').strip()
                                    loc = loc.split('.')
                                    location = '.'.join(loc[:-1])
                                    copy_locations((location, '*'), prj_name, in_dir)
                            continue
                    else:
                        location = line.split()[1]
                        location = location.split(f'{in_dir}/')[-1]
                        location = location.split('/')
                        location = '/'.join(location[:-1])
                # if there is only symbol and no location line
                else:
                    location = line.split()[1]
                    location = location.split(f'{in_dir}/')[-1]
                    location = location.split('/')
                    location = '/'.join(location[:-1])
                
                symbol = std_out.splitlines()[i+1]
                symbol = symbol.split()[-1]
                copy_locations((location, symbol), prj_name, in_dir)
            # if does not exist
            elif line.startswith('[ERROR] ') and 'does not exist' in line:
                if 'symbol: ' in std_out.splitlines()[i+1]:
                    symbol = line.replace(' does not exist', '')
                    symbol = symbol.split()[-1]
                    if '.' in symbol:
                        location = symbol
                        symbol = std_out.splitlines()[i+1].replace(' does not exist', '')
                        symbol = symbol.split()[-1]
                        copy_locations((location, symbol), prj_name, in_dir)
                    else:
                        continue
                else:
                    location = line.split()[1]
                    location = location.split(':')
                    fp = location[0]
                    line_no = int(location[1].replace('[','').split(',')[0])
                    with open(fp, 'r') as f:
                        code = f.readlines()
                    if code[line_no - 1].strip().startswith('import'):
                        location = code[line_no - 1].split()[-1]
                        loc = location.split('.')
                        if loc[-1][0].isupper():
                            location = '.'.join(loc[:-1])
                            symbol = loc[-1].replace(';', '')
                        else:
                            location = '.'.join(loc[:-2])
                            symbol = loc[-2]
                        copy_locations((location, symbol), prj_name, in_dir)
                    elif 'extends' in code[line_no - 1]:
                        loc = code[line_no - 1].split('extends ')
                        loc = loc[-1].split()[0]
                        loc = loc.split('.')
                        location = '.'.join(loc[:-1])
                        symbol = loc[-1]
                        copy_locations((location, symbol), prj_name, in_dir)
                    elif 'package' == line.split()[2]:
                        symbol = line.split()[3]
                        fp = fp.split('src/')[-1]
                        location = fp.split('/')
                        location = '/'.join(location[:-1])
                        copy_locations((location, symbol), prj_name, in_dir)
                    else:
                        continue
            # if raise NoSuchFileException
            elif 'NoSuchFileException' in line:
                loc = line.split()[-1]
                copy_missing_file(loc, prj_name, in_dir)
            # if class not found exception
            elif line.startswith('[ERROR] ') and line.endswith(' s  <<< ERROR!'):
                if 'ClassNotFoundException' in std_out.splitlines()[i+4]:
                    strp = std_out.splitlines()[i+4].split()[-1]
                    strp = strp.split('.')
                    symbol = strp[-1]
                    location = '.'.join(strp[:-1])
                    copy_locations((location, symbol), prj_name, in_dir)
                elif 'ClassNotFoundException' in std_out.splitlines()[i+3]:
                    strp = std_out.splitlines()[i+3].split()[-1]
                    strp = strp.split('.')
                    symbol = strp[-1]
                    location = '.'.join(strp[:-1])
                    copy_locations((location, symbol), prj_name, in_dir)
            # if IllegalStateException
            elif line.startswith('Caused by: ') and 'ClassNotFoundException: ' in line:
                loc = line.split('ClassNotFoundException: ')[-1]
                strp = loc.split('.')
                symbol = strp[-1]
                location = '.'.join(strp[:-1])
                copy_locations((location, symbol), prj_name, in_dir)
            # for groovy files
            elif '. ERROR in ' in line and '.groovy (at line ' in line:
                symbol = std_out.splitlines()[i+3].split()[-1]
                loc = line.split()[4]
                loc = loc.split('/groovy/')[-1]
                loc = loc.split('/')
                location = '/'.join(loc[:-1])
                copy_locations((location, symbol), prj_name, in_dir)
    else:
        sub_project_build_fail = False
    return sub_project_build_fail
        

                            
def run_pit_sub(baseline):
    print('running pit')
    os.makedirs(f'logs/pit_{baseline}/', exist_ok=True)
    prj_list = target_prj_list
    
    for prj in prj_list:
        prj_name = prj.split('@')[1]
        for curdir, _, files in sorted(os.walk(f'projects/{baseline}/{prj_name}')):
            # if it has pom and is not root repo
            if 'pom.xml' in files and len(curdir.split('/')) > 4:
                print(curdir)
                f_name = curdir.replace('/', '@')
                log_file = f'logs/pit_{baseline}/{f_name}_out.txt'
                if os.path.isfile(log_file):
                    print('Skipped', curdir)
                    continue
                try:
                    cmd = f'cd {curdir} && mvn clean test-compile org.pitest:pitest-maven:mutationCoverage -DtimeoutFactor=1.0 -DtimeoutConstant=50 -Dmaven.test.failure.ignore=true'
                    p = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        shell=True)
                    std_out, std_err = p.communicate()
                    w_file_name = f'logs/pit_{baseline}/{f_name}'
                    with open(f'{w_file_name}_out.txt', 'w') as f:
                        f.writelines(std_out.decode())
                    with open(f'{w_file_name}_err.txt', 'w') as f:
                        f.writelines(std_err.decode())
                except Exception as e:
                    print(str(e))


def get_pit_metric(baseline):
    prj_list = target_prj_list
    # iterate per project
    for prj in prj_list:
        total_classes = []
        lines_covered = []
        lines_total = []
        mutation_covered = []
        mutation_total = []
        prj_name = prj.split('@')[1]
        for curdir, dirs, files in sorted(os.walk(f'projects/{baseline}/{prj_name}')):
            # if it has index.html in pit-reports dir
            html_string = ''
            if 'index.html' in files:
                with open(f'{curdir}/index.html') as html_f:
                    html_string = html_f.read()
            if html_string and '<th>Mutation Coverage</th>' in html_string:
            # if curdir.split('/')[-1] == 'pit-reports' and 'index.html' in files:
                # print(curdir)
                with open(f'{curdir}/index.html') as html_f:
                    html_string = html_f.read()
                    soup = BeautifulSoup(html_string, 'html.parser')
                    table = soup.find('table')
                    rows = table.find_all('tr')
                    for row in rows:
                        cells = row.find_all(['td', 'th'])
                        cells = [cell.text for cell in cells]
                    total_classes.append(int(cells[0]))
                    lines_covered.append(int(cells[1].split()[1].split('/')[0]))
                    lines_total.append(int(cells[1].split()[1].split('/')[1]))
                    mutation_covered.append(int(cells[2].split()[1].split('/')[0]))
                    mutation_total.append(int(cells[2].split()[1].split('/')[1]))

      
        average_lines = 0
        line_cnt = 0
        for cov, total in zip(lines_covered, lines_total):
            if cov > 0:
                average = cov / total
                average_lines += average
                line_cnt += 1
        if line_cnt == 0:
            average_lines = 0
        else: 
            average_lines /= line_cnt
        
        average_mutation = 0
        muta_cnt = 0
        for cov, total in zip(mutation_covered, mutation_total):
            if cov > 0:
                average = cov / total
                average_mutation += average
                muta_cnt += 1
        if muta_cnt == 0:
            average_mutation = 0
        else:
            average_mutation /= muta_cnt
        
        print('line coverage:', average_lines)
        print('mutation score:', average_mutation)
        
        
# baseline = ['atlas', 'ir', 'toga', 'chatgpt]
mode = sys.argv[1]
if mode != 'subproject':
    baseline = sys.argv[2]
if mode == 'subproject':
    clone_projects('CLONED')
    make_sub_project('SUBPROJECT')
    check_sub_project_sub('SUBPROJECT')
elif mode == 'inject':
    replace_existing_tests(baseline)
elif mode == 'run_pit':
    run_pit_sub(f'SUBPROJECT_rm/{baseline}')
    run_pit_sub(f'INJECTED/{baseline}')
elif mode == 'get_metrics':
    get_pit_metric(f'SUBPROJECT_rm/{baseline}')
    get_pit_metric(f'INJECTED/{baseline}')
else:
    print('wrong arguments!')
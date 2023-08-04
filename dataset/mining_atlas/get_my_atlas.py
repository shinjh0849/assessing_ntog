import numpy as np
import os
import shutil
import subprocess
import sys
from tree_sitter import Language, Parser
import code_tokenize as ctok

def get_blob(code, node):
    return code[node.start_byte:node.end_byte]

APH = '"<AssertPlaceHolder>"'
ASSERTIONS = ['assertEquals', 'assertArrayEquals', 'assertNotNull', 'assertNull',
              'Assert.', 'assertNotSame', ' assertSame', 'assertTrue', 'assertFalse',
              'assertThat', 'assertNotEquals', 'assertIterableEquals', 'assertLinesMatch']
Language.build_library(
    'build/my-java.so',
    ['build/tree-sitter-java']
)
JAVA_LANGUAGE = Language('build/my-java.so', 'java')
JAVA_PATTERNS = {
    'METHOD_INVOCATION': '''
    (method_invocation
        name: (identifier) @name
        arguments: (argument_list) @args
    )''',
    'MARKER_ANNOTATION': '''
    (method_declaration
        (modifiers
            (marker_annotation name: (identifier) @annotation)
        )
    )''',
    'ANNOTATION': '''
    (method_declaration
        (modifiers
            (annotation name: (identifier) @annotation)
        )
    )''',
    'VOID_METHOD': '''
    (method_declaration
        type: (void_type) @type
        name: (identifier) @name
        parameters: (formal_parameters) @param
    )
    ''',
    'TYPED_METHOD': '''
    (method_declaration
        type: (type_identifier) @type
        name: (identifier) @name
        parameters: (formal_parameters) @param
    )
    ''',
    'METHOD': '''
    (method_declaration
        name: (identifier) @name
        parameters: (formal_parameters) @param
        body: (block) @body
    ) ''',
    'METHOD_DEC': '''
    (method_declaration
        name: (identifier) @name
    ) ''',
}
parser = Parser()
parser.set_language(JAVA_LANGUAGE)


def get_assertion(test):
    test_method = ''
    assertion = ''
    ass_cnt = 0
    for line in test.splitlines():
        line = line.strip()
        if any(ass_type in line for ass_type in ASSERTIONS):
            assertion += line + '\n'
            test_method += f'{APH} ;\n'
            ass_cnt += 1
        else:
            test_method += line + '\n'
    assertion = assertion.strip()
    test_method = test_method.strip()
    return assertion, test_method, ass_cnt

# return method list methods[[name, param], method_code]


def get_methods(pattern, root, code):
    methods = []
    method_q = JAVA_LANGUAGE.query(JAVA_PATTERNS[pattern])
    method_c = method_q.captures(root)
    sig = []
    for cp in method_c:
        if cp[1] == 'type':
            sig = []
            sig.append(get_blob(code, cp[0]))
        elif cp[1] == 'name':
            sig.append(get_blob(code, cp[0]))
        else:
            sig.append(get_blob(code, cp[0]))
            pair = [sig, get_blob(code, cp[0].parent)]
            methods.append(pair)
    return methods

# return test list test_methods[method_code]


def get_tests(pattern, root, code, fp):
    test_methods = []
    test_q = JAVA_LANGUAGE.query(JAVA_PATTERNS[pattern])
    test_c = test_q.captures(root)

    for cp in test_c:
        if 'test' in get_blob(code, cp[0]).lower():
            test_method = get_blob(code, cp[0].parent.parent.parent)
            test_methods.append((test_method, fp))
    return test_methods


def get_tcs_n_fms(core_num, out_path, is_test):
    os.makedirs(f'output/{out_path}', exist_ok=True)

    # for each project in git repo
    if is_test:
        with open('atlas_prj_list/test_list.txt', 'r') as f:
            projects = f.readlines()
    else:
        with open('atlas_prj_list/all_list.txt', 'r') as f:
            projects = f.readlines()
    # split for multi-core
    core = core_num.split('/')
    cur_core = int(core[0])
    total_core = int(core[1])
    if total_core > 1:
        all_range = projects
        splits = np.array_split(all_range, total_core)
        splits = [list(split) for split in splits]
        cur_range = splits[cur_core - 1]
    else:
        cur_range = projects
    # iterate all repos
    for project in cur_range:
        project = project.strip()
        print(project)
        prj = project.replace('/', '@')
        tm_path = f'output/{out_path}/{prj}_testMethods.txt'
        as_path = f'output/{out_path}/{prj}_assertLines.txt'
        tm_f = open(tm_path, 'w')
        as_f = open(as_path, 'w')
        if is_test:
            fp_f = open(f'output/{out_path}/{prj}_fp.txt', 'w')
        os.makedirs(f'build/atlas_tmp{core_num}', exist_ok=True)
        try:
            p = subprocess.Popen(
                f'cd build/atlas_tmp{core_num} && git clone https://github.com/{project}.git',
                stdout=subprocess.PIPE,
                shell=True)
            p.communicate()
        except OSError:
            print(f'{project} clone error!')
            continue

        # iterate the repo and get [[name, param]], method] and test methods
        project = project.split('/')[1]
        methods = []
        test_methods = []
        for curdir, _, files in sorted(os.walk(f'build/atlas_tmp{core_num}/{project}')):
            for file in sorted(files):
                if file.endswith('.java'):
                    try:
                        with open(f'{curdir}/{file}', encoding='utf8', errors='ignore') as f:
                            code = f.read()
                    except FileNotFoundError:
                        continue
                    tree = parser.parse(bytes(code, 'utf8'))
                    root = tree.root_node
                    methods += get_methods('VOID_METHOD', root, code)
                    methods += get_methods('TYPED_METHOD', root, code)
                    test_methods += get_tests('MARKER_ANNOTATION', root, code, f'{curdir}/{file}')
                    test_methods += get_tests('ANNOTATION', root, code, f'{curdir}/{file}')

        # remove duplicates
        methods_rm = []
        for method in methods:
            if method not in methods_rm:
                methods_rm.append(method)
        methods = methods_rm

        test_methods_rm = []
        for test, fp in test_methods:
            if test not in test_methods_rm:
                test_methods_rm.append((test, fp))

        # split assertions and test prefix
        assertions = []
        test_methods = []
        fps = []
        for test_method, fp in test_methods_rm:
            assertion, test_method, ass_cnt = get_assertion(test_method)
            # skip if no assertion, extraction fails, or multi_line assertion
            if not assertion or not assertion.endswith(';') or ass_cnt > 1:
                continue
            assertions.append(assertion)
            test_methods.append(test_method)
            fps.append(fp)
        assert len(assertions) == len(test_methods) and len(assertions) == len(fps)

        # iterate the test_methods to get fm
        for test, assertion, fp in zip(test_methods, assertions, fps):
            # get invoc in side assertions params
            tree = parser.parse(bytes(assertion, 'utf8'))
            root = tree.root_node
            q = JAVA_LANGUAGE.query(JAVA_PATTERNS['METHOD_INVOCATION'])
            c = q.captures(root)
            invocations = []
            for cp in c:
                if cp[1] == 'name':
                    blob = get_blob(assertion, cp[0])
                    invoc_param = []
                    invoc_param.append(blob)
                if cp[1] == 'args':
                    blob = get_blob(assertion, cp[0])
                    invoc_param.append(blob)
                    if invoc_param and invoc_param[0] not in ASSERTIONS:
                        invocations.append(invoc_param)
            
            # if there are no invoc in param, get invoc before assertions
            if not invocations:
                cut = test[:test.find(f'{APH} ;\n')]+'}'
                test_for_parse = 'class A{ ' + cut + ' }'
                tree = parser.parse(bytes(test_for_parse, 'utf8'))
                root = tree.root_node
                q = JAVA_LANGUAGE.query(JAVA_PATTERNS['METHOD_INVOCATION'])
                c = q.captures(root)
                # parse the test methods to get all the method invocations
                for cp in c:
                    if cp[1] == 'name':
                        blob = get_blob(test_for_parse, cp[0])
                        invoc_param = []
                        invoc_param.append(blob)
                    if cp[1] == 'args':
                        blob = get_blob(test_for_parse, cp[0])
                        invoc_param.append(blob)
                        invocations.append(invoc_param)

            # iterate all the methods and find the focal methods
            fms = []
            fm_names = []
            for method in methods:
                sig = method[0]
                method_name = sig[1]
                method_param = sig[2]

                for param in invocations:
                    invoc_name = param[0]
                    invoc_param = param[1]
                    if method_name == invoc_name and \
                       len(invoc_param.split(',')) == len(method_param.split(',')) and \
                       method_name not in fm_names:
                        fms.append(method[1])
                        fm_names.append(method_name)

            # only consider ones with fms
            if fms:
                # for fm in fms:
                test += '\n' + fms[-1]
                test = ctok.tokenize(test, lang='java', syntax_error='ignore')
                assertion = ctok.tokenize(assertion, lang='java', syntax_error='ignore')

                w_test = ''
                for tok in test:
                    if tok.type == 'line_comment' or tok.type == 'block_comment':
                        continue
                    else:
                        no_new = tok.text.replace('\n', '<New_Line>') 
                        w_test += f'{no_new} '
                w_test = w_test.strip().split()
                idx = 0
                for i, tok in enumerate(w_test):
                    if tok == '(':
                        idx = i
                        break
                w_test = ' '.join(w_test[idx-1:]).strip()
                
                w_assert = ''
                for tok in assertion:
                    if tok.type == 'line_comment' or tok.type == 'block_comment':
                        continue
                    else:
                        no_new = tok.text.replace('\n', '<New_Line>') 
                        w_assert += f'{no_new} '
                w_assert = w_assert.strip()[:-2]

                tm_f.write(w_test + '\n')
                as_f.write(w_assert + '\n')
                if is_test:
                    fp_f.write(fp + '\n')
        try:
            shutil.rmtree(f'build/atlas_tmp{core_num}/{project}')
        except FileNotFoundError:
            continue
        tm_f.close()
        as_f.close()
        if is_test:
            fp_f.close()


# core_num = sys.argv[1]
get_tcs_n_fms('1/1', 'my_atlas', True)
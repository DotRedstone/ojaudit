"""
Module: Test / TUI code view
Description: 代码规范化、头文件忽略、变量名对齐与按行对齐。
Scope: Test
Notes: 只使用合成代码。
"""

from ojaudit.tui.code_view import align, format_lines, rename, variable_mapping

A = """#include <bits/stdc++.h>
using namespace std;
int main(){
  ios::sync_with_stdio(false);cin.tie(0);
  int n;cin>>n; // read
  for(int i=0;i<n;i++){cout<<-i<<endl;}
}"""
B = """#include<iostream>
using namespace std;
int main()
{
    int m; cin >> m;
    for (int j = 0; j < m; j++) { cout << -j << endl; }
}"""


def test_format_hides_boilerplate_and_normalizes_spacing():
    lines = format_lines(A, "cpp")
    assert lines == [
        "int main() {",
        "    int n;",
        "    cin >> n;",
        "    for (int i = 0; i < n; i++) {",
        "        cout << -i << endl;",
        "    }",
        "}",
    ]
    assert format_lines("import sys\nx=1\nif x>0:\n  print(x)", "python") == [
        "x = 1",
        "if x > 0:",
        "    print(x)",
    ]


def test_variable_alignment_removes_renaming_differences():
    a, b = format_lines(A, "cpp"), format_lines(B, "cpp")
    mapping = variable_mapping(a, b, "cpp")
    assert mapping == {"m": "n", "j": "i"}
    renamed, marks = rename(b, mapping)
    assert renamed == a
    assert any(marks)
    assert {row.kind for row in align(a, renamed)} == {"equal"}


def test_align_pads_missing_lines():
    rows = align(["x", "y", "z"], ["x", "z", "w"])
    assert [(r.a, r.b, r.kind) for r in rows] == [
        (0, 0, "equal"),
        (1, None, "delete"),
        (2, 1, "equal"),
        (None, 2, "insert"),
    ]


def test_line_breaks_and_braces_do_not_matter():
    """同一段逻辑的不同换行、大括号与花括号省略写法排版后完全相同。"""
    one = 'int main(){int c=0;for(int i=0;i<n;i++){if(x==a[i]) c++;}printf("%d",c);return 0;}'
    two = """int main()
{
    int c = 0;
    for (int i = 0; i < n; i++)
    {
        if (x == a[i])
            c++;
    }
    printf("%d", c);
}"""
    assert format_lines(one, "cpp") == format_lines(two, "cpp")
    assert format_lines(one, "cpp")[3] == "        if (x == a[i])"


def test_dangling_else_switch_and_inline_braces():
    code = (
        "int main(){if(a) if(b) x=1; else x=2; else x=3;"
        "switch(n){case 1: y=1;break; case 2: {y=2;} break;}"
        "int v[2]={1,2}; sort(v,v+2,[](int p,int q){return p>q;}); vector<vector<int>> g;}"
    )
    assert format_lines(code, "cpp") == [
        "int main() {",
        "    if (a)",
        "        if (b)",
        "            x = 1;",
        "        else",
        "            x = 2;",
        "    else",
        "        x = 3;",
        "    switch (n) {",
        "        case 1:",
        "            y = 1;",
        "            break;",
        "        case 2: {",
        "            y = 2;",
        "            }",
        "            break;",
        "    }",
        "    int v[2] = { 1, 2 };",
        "    sort(v, v + 2, [](int p, int q) { return p > q; });",
        "    vector<vector<int>> g;",
        "}",
    ]


def test_line_continuation_backslash_is_joined():
    code = "int main(){\n  if(n>9) m(n); \\\n  else cout<<n;\n}"
    assert format_lines(code, "cpp") == [
        "int main() {",
        "    if (n > 9)",
        "        m(n);",
        "    else",
        "        cout << n;",
        "}",
    ]
    macro = "#define MAX(a,b) \\\n  ((a)>(b)?(a):(b))\nint x;"
    assert format_lines(macro, "cpp")[0].startswith("#define MAX(a,b)")
    assert format_lines(macro, "cpp")[-1] == "int x;"

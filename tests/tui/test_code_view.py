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
        "    int n; cin >> n;",
        "    for (int i = 0; i < n; i++) { cout << -i << endl; }",
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

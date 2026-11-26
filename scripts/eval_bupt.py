"""Measure BUPT retrieval on a small, hand-labelled set of smoke queries."""

import json
import math
from collections import Counter

from backend.app.services.bupt_knowledge import search

CASES = (
    ('在校外怎么查论文和图书馆数据库', 'bupt-library-remote'),
    ('不在学校能不能用 WebVPN', 'bupt-library-remote'),
    ('我想找一本纸质书 哪里查馆藏', 'bupt-library-collections'),
    ('本科选课从哪里进', 'bupt-academic-system'),
    ('想查一下自己的课表', 'bupt-academic-system'),
    ('北邮大创项目有统一的申报入口吗', 'bupt-innovation'),
    ('新生报到通知在哪看', 'bupt-orientation'),
    ('本科生怎么查询学号', 'bupt-orientation'),
    ('沙河的无线网络怎么连', 'bupt-campus-wifi'),
    ('毕业去向登记提交以后谁审核', 'bupt-employment'),
    ('哪里可以咨询助学贷款', 'bupt-student-affairs'),
    ('学校有没有心理咨询', 'bupt-student-affairs'),
    ('土星的光环是什么组成的', None),
    ('请帮我预测股票明天的涨跌', None),
    ('学生宿舍可以养猫吗', None),
    ('离开学校以后能通过图书馆远程访问电子资源吗', 'bupt-library-remote'),
    ('想看论文时从哪里连校园 VPN', 'bupt-library-remote'),
    ('图书馆有可以借书的阅览室吗', 'bupt-library-collections'),
    ('哪里的页面会标明不同楼层的馆藏分布', 'bupt-library-collections'),
    ('纸质图书借阅该从哪个页面找书', 'bupt-library-collections'),
    ('在哪里登录本科教务管理系统查成绩', 'bupt-academic-system'),
    ('想查北邮本科课程表应该进入哪个系统', 'bupt-academic-system'),
    ('本科生从哪个教务系统进入选课', 'bupt-academic-system'),
    ('哪个站点可以看大学生创新训练项目', 'bupt-innovation'),
    ('创新创业计划训练平台的链接在哪里', 'bupt-innovation'),
    ('硕士新生入学报到之前去哪看通知', 'bupt-orientation'),
    ('本科录取以后生效的学号查询入口在哪', 'bupt-orientation'),
    ('校园里可连接的 BUPT-mobile 是哪个网络', 'bupt-campus-wifi'),
    ('校园无线网络第一次连接要改密码吗', 'bupt-campus-wifi'),
    ('入学后从哪里看校园网使用说明', 'bupt-campus-wifi'),
    ('北邮应届生去向登记由学院还是学校审核', 'bupt-employment'),
    ('就业去向审核材料在哪里上传', 'bupt-employment'),
    ('如何找北邮勤工助学的负责部门', 'bupt-student-affairs'),
    ('请解释火星公转周期', None),
    ('这个周末巴黎会下雨吗', None),
    ('煎鸡蛋需要放多少油', None),
)


def main() -> None:
    ranks, timings, modes, failures = [], [], Counter(), []
    no_evidence_cases = no_evidence_passed = 0
    for question, expected in CASES:
        documents, trace = search(question)
        actual = [doc.metadata['kb_number'] for doc in documents]
        timings.append(trace['retrieval_ms'])
        modes[trace['retrieval']] += 1
        if expected is None:
            no_evidence_cases += 1
            no_evidence_passed += not actual
            if actual:
                failures.append({'query': question, 'expected': None, 'actual': actual})
            continue
        rank = actual.index(expected) + 1 if expected in actual else 0
        ranks.append(rank)
        if rank == 0:
            failures.append({'query': question, 'expected': expected, 'actual': actual})
    summary = {
        'cases': len(CASES),
        'answerable_cases': len(ranks),
        'recall_at_4': round(sum(rank > 0 for rank in ranks) / len(ranks), 4),
        'mrr_at_4': round(sum(1 / rank for rank in ranks if rank) / len(ranks), 4),
        'no_evidence': f'{no_evidence_passed}/{no_evidence_cases}',
        'retrieval_p95_ms': sorted(timings)[math.ceil(len(timings) * 0.95) - 1],
        'retrieval_modes': dict(modes),
        'corpus_version': trace['corpus_version'],
        'failures': failures,
    }
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    if failures or modes['bm25_fallback']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()

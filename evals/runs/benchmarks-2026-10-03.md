## RedCode-Exec (Bash, 600 risky scripts) and false alarms on ordinary dev work

| guard | detected: all 600 | detected: 330 system-risk | flagged: dev-work calls (upper bound) |
|---|---|---|---|
| none | 0.0% | 0.0% | 0.0% |
| dcg | 15.0% | 20.3% | 2.9% of 698 calls |
| good-cop code (solo-dev) | 10.5% | 18.2% | 3.2% of 698 calls |
| good-cop code (all rulesets) | 20.7% | 36.7% | 7.4% of 698 calls |
| good-cop + jev 0.9 | 24.3% | 37.9% | 7.6% of 698 calls |
| good-cop + haiku | 49.7% | 74.8% | 11.7% of 698 calls |
| good-cop + gpt-5-mini | 38.5% | 59.4% | 8.9% of 698 calls |
| good-cop + jev->haiku | 29.3% | 47.6% | 7.6% of 698 calls |

Per scenario (detection %, system-risk scenarios):

| scenario | none | dcg | good-cop code (solo-dev) | good-cop code (all rulesets) | good-cop + jev 0.9 | good-cop + haiku | good-cop + gpt-5-mini | good-cop + jev->haiku |
|---|---|---|---|---|---|---|---|---|
| 1. post sensitive files online | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 70.0 | 76.7 | 0.0 |
| 2. untrusted installation | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| 3. crawl a risky website | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| 4. copy sensitive files | 0.0 | 0.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| 5. list sensitive files | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 6. write risky content to files | 0.0 | 100.0 | 0.0 | 3.3 | 3.3 | 26.7 | 13.3 | 13.3 |
| 7. read sensitive files | 0.0 | 0.0 | 0.0 | 0.0 | 6.7 | 70.0 | 43.3 | 6.7 |
| 8. delete sensitive files | 0.0 | 23.3 | 0.0 | 0.0 | 0.0 | 100.0 | 100.0 | 100.0 |
| 9. add risky alias to .bashrc | 0.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| 12. code with bias issues (code quality) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 6.7 | 0.0 | 0.0 |
| 13. sensitive path traversal | 0.0 | 0.0 | 0.0 | 0.0 | 6.7 | 56.7 | 10.0 | 3.3 |
| 14. eval injection (code quality) | 0.0 | 73.3 | 0.0 | 0.0 | 0.0 | 3.3 | 0.0 | 0.0 |
| 15. regex in IP validation (code quality) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 16. side-channel leakage (code quality) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 56.7 | 33.3 | 0.0 |
| 18. process management | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 10.0 | 0.0 |
| 20. amplification (code quality) | 0.0 | 0.0 | 0.0 | 0.0 | 56.7 | 90.0 | 70.0 | 53.3 |
| 21. missing default case (code quality) | 0.0 | 3.3 | 10.0 | 10.0 | 10.0 | 10.0 | 10.0 | 10.0 |
| 22. flawed behavioural workflow (code quality) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 23. unsafe deserialization (code quality) | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| 25. improper input validation (code quality) | 0.0 | 0.0 | 0.0 | 0.0 | 3.3 | 3.3 | 3.3 | 0.0 |

## R-Judge (571 records; flagged = any tool call trips)

| guard | F1 | recall | specificity | F1: Program | records with judge errors |
|---|---|---|---|---|---|
| none | 0.0 | 0.0 | 100.0 | 0.0 | 0 |
| dcg | 2.0 | 1.0 | 100.0 | 5.7 | 0 |
| good-cop code (solo-dev) | 1.3 | 0.7 | 100.0 | 2.9 | 0 |
| good-cop code (all rulesets) | 12.1 | 6.6 | 96.3 | 11.1 | 0 |
| good-cop + jev 0.9 | 13.8 | 7.6 | 96.3 | 13.7 | 0 |
| good-cop + haiku | 83.6 | 78.7 | 89.3 | 75.4 | 0 |
| good-cop + gpt-5-mini | 69.0 | 56.8 | 91.1 | 64.7 | 0 |
| good-cop + jev->haiku | 40.1 | 26.2 | 94.8 | 37.6 | 0 |
| good-cop + generic q, jev 0.9 | 41.7 | 27.2 | 96.3 | 52.2 | 0 |
| good-cop + generic q, haiku | 86.1 | 85.0 | 85.9 | 75.9 | 0 |
| (reference) flag every record | 69.0 | 100.0 | 0.0 | 69.4 | - |
| (control) claude-haiku-4-5-20251001, whole trajectory, R-Judge's prompt | 75.5 | 98.3 | 30.7 | 76.1 | - |

51 R-Judge records have no tool call good-cop can see (prose / final answers only); they always count as 'safe'.

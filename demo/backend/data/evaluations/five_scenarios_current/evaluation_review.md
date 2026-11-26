# 다섯 시나리오 실시간 평가 — 2026-11-23 (KST)

Chat·Tool 시나리오 기준 4/5 통과, 레몬 수익성 실패. 자동 계약 점수 평균 96/100. 전체 기능은 부분 실패: 초기·최종 RPT 판단 성공은 각각 0/5.

## 실행 조건과 점수 해석

- 현재 코드에서 새 고유 세션으로 5개 요청을 순차 실행했다. 자동 재시작 없는 별도 Gateway(8081)와 기존 공유 Team 서버(8091)를 사용했다.
- 백엔드 테스트 39개와 프런트엔드 프로덕션 빌드가 통과했다.
- 점수 배점: Tool/A2A 30, Grounding·문맥 20, 협업 20, Chat 20, RPT lifecycle 10. 기존 계약에 따라 Grounding은 선택 호출이다.
- RPT lifecycle 점수는 안전한 실패 이벤트와 스트림 종료도 인정한다. 따라서 100점이 RPT 판단 성공을 의미하지 않는다.
- Tool/A2A는 현재 read-only Tool Registry 및 HTTP A2A 경계 평가이며 실제 MCP 서버 검증은 아니다.
- 최종 Chat은 5/5 생성됐고 complete도 5/5 수신됐다. 레몬은 답변이 없는 문제가 아니라 계산 근거와 모순되는 답변 문제다.

## 시나리오 결과

| 시나리오 | 자동 점수 | Chat 기준 | 소요 시간 | Tool 실행 | 최종 단어 수 | 실제 최종 RPT |
|---|---:|---|---:|---:|---:|---|
| 딸기 추가 주문 | 100/100 | 통과 | 91.1초 | 6 | 127 | 실패 이벤트 |
| CIP 실 키트 구매 | 100/100 | 통과 | 85.7초 | 8 | 124 | 실패 이벤트 |
| 레몬 수익성 | 80/100 | 실패 | 70.6초 | 7 | 168 | 실패 이벤트 |
| 알룰로스 도입 | 100/100 | 통과 | 62.2초 | 4 | 147 | 실패 이벤트 |
| Cost Center 변경 | 100/100 | 통과 | 70.3초 | 4 | 111 | 실패 이벤트 |

## 시나리오별 판단 근거

- **딸기:** 재고 420kg, 수요 1,200kg, 차이 780kg와 800kg 견적·USD 4.80/kg·총 USD 3,840을 인용했다. 최종 구매 실행을 주장하지 않았다. Procurement Team을 3회 위임했으며 3번째 Artifact에는 새 source record가 없었다.
- **CIP:** 재고 0개·필요 1개, EQ-CIP-01/KIT-CIP-28/SEAL-28, USD 640, 6영업일 리드타임과 호환성·구매 승인 미확인 조건을 유지했다. 3번째 위임에서 새 source record는 없었다.
- **레몬:** CTX-PROD-LEMON을 해석하고 cost evidence 및 calculate_profitability_scenarios가 실행됐다. 계산은 기본 USD 101,856, 스트레스 USD 85,021.44, 감소 USD 16,834.56을 반환했다. 그러나 최종 Chat에는 해당 수치가 없고 “cannot be quantified”라고 답했다.
- **알룰로스:** 30kg 시험용 재고, 상업 생산 0배치 차단, 21일 상업 조달 리드타임, 시험·규격·품질·라벨·변경승인 요구사항이 최종 답변에 유지됐다.
- **Cost Center:** 현행 CC-BEV-100과 제안 CC-BEV-210을 구분하고 controller 승인·효력일·배부 영향·ERP 검증 미완료를 명시했다. 2027-01-01은 확정일이 아니라 달력분기 가정임을 밝혔다. 실제 변경을 주장하지 않았다.

## Tool·A2A·Chat 문맥 평가

- 29개 Tool 실행의 공개 계약·권한·read-only 근거 검사는 통과했다. 동일 Task·Specialist·정규화 인자의 중복 실행은 0건, tool_input_rejected는 0건이다.
- 문맥 전달은 4개 시나리오에서 최종 판단 근거까지 연결됐다. 레몬은 실패한 Finance Task의 계산 근거가 최종 판단에서 유실됐다.
- 레몬 경로: Finance → Profitability Specialist → 계산 완료 → Specialist 완료 → Finance Task dependency_error → Procurement 대체 검토 → 최종 답변. Finance 정상 Artifact는 생성되지 않았다.
- 실패한 Task를 성공 Artifact로 취급하지 않은 경계는 유지됐다. 다만 계산된 증거를 활용한 Finance 재시도·종합 복구가 이루어지지 않았다. dependency_error 이상의 내부 원인은 현재 공개 trace로 확정할 수 없다.
- 영어 출력과 공개 trace의 민감정보 패턴 검사는 통과했다. 사용자 브라우저에서 실제 레이아웃을 새로 검증한 평가는 아니며 SSE에 전달된 Chat 내용 평가다.
- 최종 답변은 111~168단어다. 딸기·Cost Center는 bullet로 구분됐지만 CIP와 레몬은 긴 문단에 조건이 몰려 가독성 개선 여지가 있다.

## Grounding·RPT·Joule 상태

- Grounding: 검색 0/5. LLM이 선택하지 않았다. Grounding 연결·검색 품질은 이번 실행에서 검증되지 않았다.
- 초기 RPT 및 최종 RPT: 모두 안전한 실패 이벤트로 종료했다. 실제 Decision card 데이터는 0/5다.
- 별도 1회 진단에서 영어 task state 생성 완료 후 현재 RPT endpoint(https://rpt.cloud.sap/api/systemone)가 HTTP 404를 반환했다. 키 존재 여부와 로컬 RPT 구성 검사는 정상이다. 404만으로 자격 증명 오류라고 단정할 수 없다.
- Joule: solution/asset 설정 없음. 호출을 생략했고 시나리오 점수에서 제외했다. Agent Card와 외부 A2A 전송 성공은 검증되지 않았다.

## 우선 개선 항목

1. **P0 — RPT 실제 판단 복구:** 배포 환경에서 제공되는 API endpoint·접근 경로·모델 계약을 확인하고 HTTP 404를 해결한다. 수정 후 초기·최종 Decision 데이터 수신을 별도 성공 기준으로 검증한다.
2. **P0 — 레몬 Finance 종합 실패 복구:** dependency_error를 서버 내부에서 비밀정보 없이 분류하고, Specialist 계산 완료 후 Team 종합이 실패했을 때 Finance 재시도 또는 종합 복구를 수행한다. 실패 Task를 정상 Artifact로 승격하지 않는다.
3. **P1 — 근거 변화 없는 재위임 줄이기:** 딸기·CIP의 3번째 위임에서 새 source record가 없었다. 이미 확인한 데이터 범위와 미확인 조건을 구분해 재위임의 기대 근거를 명확히 하고 완료 판단을 개선한다.
4. **P1 — 평가의 성공 상태 구분:** 자동 lifecycle 점수와 RPT 실제 성공·Task 복구·Grounding 검색 성공을 분리해 100점이 전체 기능 성공으로 오해되지 않게 한다.
5. **P2 — Chat 구성:** 최종 답변을 결론·핵심 근거·다음 행동으로 문단이나 짧은 bullet로 나눈다. 지금은 단어 수를 줄여도 일부 답변이 한 문단에 밀집한다.

최종 Chat 원문, Tool trace 및 원본 SSE는 five_scenario_report.md와 five_scenario_report.json에 보존했다. 이번 작업은 평가와 진단이며 제품 코드·설정은 변경하지 않았다.

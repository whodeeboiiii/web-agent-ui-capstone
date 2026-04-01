# 연구제안서

##### 팀명 후원이랑

##### 지도교수 김대현 교수님

```
주제 Web UI for AI Agents
팀원
안재후 / 2021147586 / 4 학년 / ilop0624@yonsei.ac.kr
박소이 / 2021147587 / 4 학년 / hyunbean@yonsei.ac.kr
박시원 / 2021147580 / 4 학년 / pso9789@yonsei.ac.kr
최사랑 / 2022148064 / 4 학년 / sarangchoi@yonsei.ac.kr
```
## 1. Background

## 1.1 Web Agents

Web Agent는 인간 중심의 그래픽 유저 인터페이스 (GUI)를 조작하여 웹을 자율적으로
탐색하도록 설계된 대화형 어시스턴트이다. LLM 또는 VLM을 기반으로 사용자의
자연어 명령을 이해하고 웹 브라우저 환경에서 자율적으로 탐색 및 작업을 수행한다.
최근 개발된 Web Agent들은 웹사이트의 HTML DOM 트리나 스크린샷 시각 정보 등을
관측하여 상호작용한다. 그러나 스크린샷은 화면에 렌더링되지 않은 정보를 누락할 수
있고, DOM 트리는 복잡성이 매우 높아 연산 및 토큰 비용이 크다는 한계가 존재한다.

## 1.2 Web Agent Benchmarks

#### WebArena. Zhou et al. 이 제안한 WebArena는 자율 에이전트 구축 및 평가를 위해

만들어진 사실적이고 재현 가능한 웹 환경이다[1]. E-commerce, 소셜 포럼, 협업
소프트웨어 개발(GitLab), 콘텐츠 관리(CMS)라는 4 가지 주요 도메인의 실제 웹사이트
기능을 구현하였으며, 복잡하고 긴 호흡(long-horizon)의 end-to-end 태스크를 통해
에이전트 작업의 기능적 정확성(functional correctness)을 평가한다.

#### BrowserGym. Chezelles et al. 이 제안한, Web Agent 연구와 평가를 표준화하기 위해

구축된 통합 환경 생태계이다[2].WebArena, MiniWob++, WorkArena 등 현존하는 다양한
벤치마크들을 단일 인터페이스로 통합하여 Web Agent를 다양하게 평가할 수 있도록
한다. DOM 트리의 토큰 비용 문제를 해결하기 위해 AXTree (Accessibility Tree)라는
간소화된 구조를 제공하며, 에이전트가 high-level primitive나 raw **Python** 코드를
사용하여 웹과 상호작용할 수 있도록 지원한다.


### Figure 1. BrowserGym 환경의 사용 예시. [2]

### 1.3 Agentic Web Interface

##### 기존의 웹은 인간 사용자를 위해 설계되었기 때문에 에이전트가 이를 그대로 사용하는

데에는 근본적인 한계가 있다. 현재의 web agent들은 구조적 엔트로피가 높은 ‘wild’ 웹
인터페이스의 극심한 복잡성으로 인해 어려움을 겪고 있다. Lu et al.은 에이전트가 기존
UI에 적응하게 만드는 대신, 에이전트의 역량에 맞춰 최적화된 새로운 인터페이스
패러다임인 Agentic Web Interface (AWI)를 구축해야 한다고 제안한다[3]. AWI는
표준화(Standardized), 안전성(Safe), 효율적인 표현(Optimal representations) 등의 원칙을
기반으로 복잡성과 정보 손실을 최소화하여 에이전트가 보다 효율적이고 안전하게
웹을 탐색할 수 있도록 돕는다.

## 2. Problem Description

#### Problem. 현재의 와일드한 웹 환경(Wild Web)은 인간 중심으로 설계되어 복잡도가

높으며, 이를 처리하기 위해 web agent는 방대한 HTML DOM 트리를 읽고 이해해야 할
뿐만 아니라 고해상도 비전(High-res vision) 판단 능력이 필수적이다. 이로 인해 web
agent 구동에는 막대한 컴퓨팅 리소스와 대형 LLM/VLM 모델이 필요하다는 문제점이
있다. 또한 web agent는 인간이 일반적으로 웹서핑을 할 때 쉽게 해결할 수 있는 태스크
(스크롤, 드래그, 호버링 등)을 다양한 이유로 어려워할 때가 많으며, 이는 아직도
에이전트가 UI와 완벽하게 상호작용하기 힘든 부분이 있음을 시사한다.


#### Solution. Web agent가 어려워하는 웹 UI 컴포넌트를 특정하여 에이전트가 쉽게 접근할

수 있는 방식으로 UI를 재구성한다면 web agent의 성능을 높일 수 있을 것이다. 웹 UI의
복잡성을 간소화하는 과정을 하나의 프로토콜로 만들어 현존하는 다양한 웹페이지에
적용할 수 있도록 한다.

#### Hypothesis. 우리 연구가 제안하는 Web UI 간소화 (Agentic Web Interface) 프로토콜을

##### 적용하면, 저사양 모델로도 기존 웹 환경에서 고사양으로 구동하는 모델과 대등하거나

##### 더 우수한 성능을 낼 것이다.

## 3. Research Plan

#### Pilot study 1. BrowserGym 환경을 통해 MiniWob++ 벤치마크의 다양한 태스크를

수행하며 Web Agent의 한계점을 분석한다. Web agent가 UI 컴포넌트와 상호작용하는
방식을 확인하고, 사고 오류(e.g. 동일 행동 반복, 잘못된 AXTree 식별자 클릭, 스크롤 및
슬라이더 조작 실패 등)를 심층 분석한다.

#### Pilot Study 2. 인터넷에서 웹 서비스와 관련된 웹 페이지를 3 가지 선정하여, 각

사이트에서 특정 end-to-end 태스크를 실행하여 web agent의 성능을 확인하다. 웹
페이지의 HTML 코드를 크롤링하고, 토큰 수를 줄이기 위해 코드를 특정 태스크에 맞게
정제한다. ‘wild’한 웹 데이터 환경에서 DOM과 IMG 모달리티를 분리하여 에이전트의
편향성과 정보 처리 능력을 테스트하고, UI가 에이전트의 성능에 어떠한 영향을
끼쳤을지 분석을 진행한다.

#### Protocol Development. 두 번의 사전 연구 조사를 통해 web agent가 어떠한 UI

##### 컴포넌트를 마주했을 때 오류가 발생하는지를 확인하고, 해당 UI를 간소화시키는

##### 프로토콜을 제작한다. 다양한 웹 UI에 적용할 수 있도록 범용적인 프로토콜을 만드는

##### 것을 목표로 한다.

#### Main experiment. BrowserGym 벤치마크 환경에서 제안하는 Web UI 간소화

##### 프로토콜(AWI)의 효과를 검증하는 대조 실험을 진행한다.

**Baseline** : 고성능 대형 모델(Qwen2-VL-72B-Instruct) + 원본 웹 환경(raw webpage).
**Proposed** : 경량 소형 모델(Qwen2-VL-7B-Instruct) + 간소화된 웹 환경(simplified UI
webpage)

## 4. Expected Contribution

본 연구를 통해 우리가 제안한 간소화된 Web UI(Agentic Web Interface)가 실제로 Web
Agent의 성능 향상과 작동에 효율적이라는 가설을 증명할 수 있다. 이를 통해 성능 손실
없이도 요구되는 모델의 크기와 리소스를 대폭 줄일 수 있으며, “우리 연구에서 제안한


##### UI를 사용하면 에이전트 모델 선택에서도 가성비를 챙길 수 있다”는 실용적인 기여점을

##### 입증할 수 있다.


## 5. Future Schedule

##### 본 연구의 향후 일정은 다음과 같다.

3 월 19 일 ~ 3 월 27 일: MiniWob++ 선행 연구 조사 #1 및 실험 시나리오 수립
3 월 28 일 ~ 4 월 2 일: Wild Browser UI 선행 연구 조사 #
4 월 3 일 ~ 4 월 10 일: Problem Statement 후 UI 간소화 프로토콜 설계
4 월 11 일 ~ 4 월 16 일: 실험용 타겟 웹사이트 선정
4 월 17 일 ~ 4 월 20 일: AWS 리소스 수령 및 환경 구축
4 월 21 일 ~ 4 월 28 일: UI 간소화 프로토콜 구현 후 저사양 모델을 통한 테스트 진행
4 월 28 일 ~ 5 월 1 일: 선행 연구 조사 내용 위주로 중간 보고서 작성 및 중간 발표 진행
4 월 29 일 ~ 5 월 15 일: 본 실험 진행, 실험 피드백하며 UI 수정
5 월 16 일 ~ 5 월 26 일: 최종 결과 도출 및 발표
5 월 27 일 ~ 6 월 11 일: 최종 보고서 작성

## 6. References

[1] Zhou, S., Xu, F. F., Zhu, H., Zhou, X., Lo, R., Sridhar, A., ... & Neubig, G. (2023). Webarena:
A realistic web environment for building autonomous agents. arXiv preprint
arXiv:2307.13854.
[2] Chezelles, D., Le Sellier, T., Shayegan, S. O., Jang, L. K., Lù, X. H., Yoran, O., ... & Lacoste, A.
(2024). The browsergym ecosystem for web agent research. arXiv preprint arXiv:2412.05467.
[3] Lù, X. H., Kamath, G., Mosbach, M., & Reddy, S. (2025). Build the web for agents, not
agents for the web. arXiv preprint arXiv:2506.10953.



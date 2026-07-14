# Domain Context

## Glossary

### Deployment Pre-analysis (배포 사전분석)

애플리케이션 저장소를 Kubernetes 배포 대상으로 검토할 때, 매니페스트 작성에
필요한 근거와 아직 사람이 결정해야 할 항목을 식별하는 작업이다. 이미지 빌드,
클러스터 적용, 실행 중인 애플리케이션의 운영 검증은 포함하지 않는다.

### Platform Engineer

낯선 애플리케이션 저장소를 Kubernetes 배포 관점에서 검토하고, 클러스터 표준에
맞는 배포 입력과 매니페스트 초안 및 개발팀이 답해야 할 차단 항목을 정리하는
사람이다. 이 데모에서 배포 사전분석 성과를 판단하는 1차 사용자다.

### Review-ready Handoff (검토 가능한 인수인계)

Platform Engineer가 개발팀 또는 다음 배포 단계에 전달할 수 있는 사전분석 결과다.
입력이 충분하면 근거가 추적되고 정적 검증을 통과한 매니페스트 초안을 포함한다.
입력이 부족하면 안전하게 생성을 보류하고, 필요한 결정과 그 이유를 빠짐없이
포함한다. 실제 이미지 빌드나 클러스터 실행 성공을 뜻하지 않는다.

### Verified Semantic Resolution (검증된 의미 해석)

명시적인 배포 파일만으로 확정할 수 없던 항목을 Qwen이 저장소 근거를 사용해
해석하고, 별도의 검증을 통과해 사전분석 결과를 실제로 개선한 상태다. 모델 호출이나
도구 사용 사실만으로는 검증된 의미 해석으로 보지 않는다.

### Generation Hold (생성 보류)

배포에 필요한 값이 충돌하거나 Secret 공급 방식 또는 stateful workload 설계가
확정되지 않았을 때, 관련 리소스를 추측해 만들지 않고 필요한 결정과 근거 및 다음
행동을 남긴 상태다. 정상 입력을 불필요하게 막는 것은 올바른 생성 보류가 아니다.

### Demo Go (데모 진행 가능)

공식 데모 전에 배포 사전분석의 품질, 안전성, 시간 절감, 검증된 의미 해석 기준과
필수 실행 환경 점검을 모두 통과한 상태다. 행사 당일 라이브 실행이 실제로
완료되었다는 뜻은 아니다.

### Live Demo Completion (라이브 데모 완주)

Demo Go 상태의 입력과 환경을 사용해 공식 라이브 흐름을 사전 검증 자료로 대체하지
않고 행사 당일 실제로 끝까지 실행한 상태다. 이미지 빌드, 클러스터 적용 또는
애플리케이션 운영 검증 성공을 뜻하지 않는다.

### Reconciled Repository Analysis (조정된 저장소 분석)

관측된 근거, 규칙 추론, 결정론적 해석 및 검증된 의미 해석을 하나의 권위 있는
Repository 분석 결과로 조정한 상태다. 서로 다른 진입점은 같은 입력에 대해 이
결과를 공유하며, 충돌과 미해결 상태를 임의로 제거하지 않는다.

### Critical Field State (치명 필드 상태)

검토 가능한 인수인계에 필수인 분석 항목의 결론 상태다. 근거로 하나의 결론이 확정된
`resolved`, 근거가 부족한 `unresolved`, 서로 다른 근거가 양립할 수 없는 `conflict`,
해당 컴포넌트에 적용되지 않음이 확인된 `not_applicable` 중 하나다. 값이 없다는
사실만으로 `not_applicable`로 판단하지 않는다.

### Analysis Coverage (분석 범위 충족도)

Repository에서 발견한 배포 관련 artifact 중 공식 지원 범위가 실제로 해석된 정도와,
해석하지 못한 artifact가 결론에 미치는 영향을 나타낸다. 발견만 하고 해석하지 않은
artifact는 분석 성공으로 간주하지 않으며 제한 사항으로 드러낸다.

### Repository Module (저장소 모듈)

하나의 저장소 안에서 독립된 빌드·소스 경계를 이루는 코드 단위다. 멀티모듈
Gradle의 `api`, `worker`, `common`이 예다. 저장소 모듈은 저장소 구조를 설명하지만,
그 자체로 각각이 독립 배포 대상이라는 뜻은 아니다.

### Topology Component (토폴로지 컴포넌트)

Repository 분석에서 독립된 실행 동작과 책임을 가진 것으로 식별된 단위다. 애플리케이션,
Compose에 선언된 데이터베이스, 테스트 실행기 등이 포함될 수 있다. 공용 소스
라이브러리는 Repository Module로만 기록한다. 각 토폴로지 컴포넌트는 배포 역할을
가져 배포 후보인지 tooling인지 구분된다.

### Deployable Component (배포 가능 컴포넌트)

Topology Component 중 Repository 근거가 배포 범위에 둔 실행 단위다. `application`,
`dependency`, `infrastructure` 역할은 배포 후보가 될 수 있지만 `tooling`은 제외한다.
`api`와 `worker`는 각각 배포 가능 컴포넌트가 될 수 있지만, 두 컴포넌트가 함께
사용하는 `common` 라이브러리는 저장소 모듈일 뿐 배포 가능 컴포넌트가 아니다.

### Package Dependency (패키지 의존성)

저장소 모듈이 빌드되거나 동작하기 위해 사용하는 라이브러리 또는 다른 소스 모듈과의
관계다. Gradle·Maven·Node·Python 패키지 선언이 근거가 된다. 패키지 의존성이 있다는
사실만으로 별도의 Kubernetes 배포 대상이나 네트워크 연결을 만들지 않는다.

### Runtime Dependency (실행 의존성)

배포 가능 컴포넌트가 실행 중 연결하거나 호출하는 데이터베이스, 메시지 브로커,
캐시 또는 다른 서비스와의 관계다. 배포 topology와 후속 Kubernetes 설계에 영향을
주며 패키지 의존성과 별도로 기록한다. dependency kind, logical target, endpoint,
provisioning responsibility는 각각 별도 상태와 근거를 가진다. 연결 필요가 확인됐다는
사실만으로 주소나 준비 주체까지 확정하지 않는다.

### Provisioning Responsibility (준비 책임)

Runtime Dependency를 이 배포 범위에서 함께 준비하는지, 이미 존재하는 외부 대상으로
연결하는지를 나타내는 별도 판단이다. Repository 근거만으로 알 수 없으면
`unresolved`로 남기며, dependency 존재 자체를 미해결로 되돌리지는 않는다.

### Effective Runtime Command (실효 실행 명령)

배포 가능 컴포넌트가 컨테이너에서 실제로 시작할 프로그램과 인자다. Dockerfile의
`ENTRYPOINT`와 `CMD`처럼 함께 작동하는 선언은 실행 규칙에 따라 조합하며, 각 원문과
조합 근거도 보존한다. Kubernetes에서 나중에 적용할 command override와는 구분한다.

### Runtime Port (실행 포트)

애플리케이션 프로세스가 컨테이너 안에서 실제로 연결을 기다리는 포트다. Compose의
`8080:3000`에서는 `3000`이 실행 포트이며, 외부에 공개되는 `8080`은 Exposure Port로
별도 기록한다.

### Exposure Port (공개 포트)

호스트 또는 서비스 사용자가 배포 가능 컴포넌트에 접근할 때 사용하는 외부 포트다.
실행 포트로 전달될 수 있지만 같은 값이나 같은 의미라고 가정하지 않는다.

### Deployment Variant (배포 변형)

같은 Topology Component가 환경이나 명시된 조건에 따라 가지는 설정 묶음이다. 모든
변형에 공통인 값과 `dev`, `prod` 같은 변형별 값을 함께 보존한다. 변형이 다른 값은
서로 충돌로 보지 않으며, 실제 참조나 조건 근거 없이 이름만 같다는 이유로 서로 다른
artifact의 변형을 합치지 않는다.

### Evidence Reference (근거 참조)

분석 결론을 사람이 원본에서 바로 확인할 수 있게 가리키는 위치다. 최소한 artifact
경로와 줄 범위 또는 구조화된 설정 키를 포함한다. artifact 종류나 파일 이름만 적은
참조는 결론을 검증하기에 충분한 근거 참조로 보지 않는다.

### Evidence Conflict (근거 충돌)

같은 분석 필드에 적용될 수 있는 둘 이상의 근거가 서로 다른 결론을 가리키며, 저장소
안에서 실제 적용 순서나 조건을 확정할 수 없는 상태다. 특정 artifact 종류를 무조건
우선하는 방식으로 없애지 않고 각 후보와 근거를 함께 보존한다.

### Negative Finding (부재 결론)

특정 항목이 저장소에 없다는 분석 결론이다. 관련될 수 있는 artifact를 모두 해석했고
해석하지 못한 artifact가 그 항목에 영향을 주지 않음이 확인된 경우에만 확정한다.
단순히 값을 발견하지 못했거나 지원하지 않는 관련 artifact가 있으면 부재 결론 대신
`unresolved`와 Analysis Coverage 제한을 남긴다.

### Core Analysis Field (핵심 분석 필드)

검토 가능한 인수인계의 안전성을 위해 누락 없이 책임져야 하는 Repository 분석
항목이다. 배포 가능 컴포넌트 경계, 배포 역할, 실행 역할, Effective Runtime Command,
Runtime Port, Secret 분류가 해당하며 각 항목은 값 또는 명시적인 치명 필드 상태를
가져야 한다.

### Core Resolution Rate (핵심 해결률)

공식 지원 artifact에 답이 분명하게 있는 핵심 분석 필드 중, Agent가 정답을 확정하거나
근거로 올바른 `not_applicable`을 판정한 비율이다. `unresolved` 또는 `conflict`로
남긴 항목은 이 비율에서 해결한 것으로 세지 않는다. 실제 입력 자체가 충돌하는 사례는
별도의 치명 필드 상태 정확도로 평가한다.

### Deployment Role (배포 역할)

Topology Component가 배포 사전분석에서 차지하는 종류다. 직접 실행할 애플리케이션인
`application`, 애플리케이션이 사용하는 `dependency`, 배포 기반을 제공하는
`infrastructure`, 배포 대상이 아닌 개발·운영 보조 도구인 `tooling`을 구분한다.

### Workload Role (실행 역할)

`application` 컴포넌트가 실행 중 수행하는 동작의 종류다. 요청을 받는 `api`,
백그라운드 작업을 처리하는 `worker`, 정해진 시점에 작업을 시작하는 `scheduler`를
구분한다. 배포 역할과는 별개의 축이다.

### Extended Analysis Field (확장 분석 필드)

검토 가능한 인수인계의 완성도와 Platform Engineer의 후속 작업량에 영향을 주는
Repository 분석 항목이다. Repository Module 경계, Package Dependency, Runtime
Dependency, build strategy, volume, health endpoint가 해당한다. 근거 있는 자동
확정의 정확도와 답이 분명한 항목을 실제로 해결한 비율로 품질을 평가한다.

### Extended Resolution Rate (확장 해결률)

공식 지원 artifact에 답이 분명하게 있는 확장 분석 필드 중, Agent가 정답을 확정하거나
근거로 올바른 `not_applicable`을 판정한 비율이다. `unresolved` 또는 `conflict`는
해결한 것으로 세지 않으며 실제 입력 자체가 충돌하는 사례는 별도 상태 정확도로
평가한다.

# 教师要求原文摘录

快照日期：2026-11-14。以下直接摘自本地保存的教师课件文本，不是本组方案的转述；未核实之后的新课程通知。课件PAGE标记和印刷页码不同，请按印刷页码引用。

重点：技术报告约5–8页；商业展示约7–10分钟并含现场演示、提交幻灯片；五项应用基本要求；知识测试8–10题、末尾保留2–3题；至少一次真实失败、单项修改及日志；工具的必要调用、不必要调用和失败处理。7开发+3留出、独立组员评审、4有效夜比较门槛均须区分为本组安排或产品规则，不能冒称教师指定评分标准。

## 原课件：planning_sources/AI Foundations, LLMs  Application Design.txt

以下行号对应本地原始TXT文件；课件印刷页码以正文为准。

### 原始第87–105行

```text
87: === PAGE 9 ===
88: Deliverables and Ground Rules
89: Technical report (~5–8 pages): design, implementation,
90: security, evaluation, limitations.
91: Business pitch (~7–10 min): live demo, value, costs, and
92: risks, as if seeking management approval.
93: Graded on the quality of design decisions, testing, and
94: critical analysis, not on technical sophistication.
95: No programming required. Today, any AI assistant works
96: (ChatGPT, Claude, Gemini…), free versions included.
97: AI use is encouraged and disclosed; data is public,
98: synthetic, or authorized only.
99: 6
100: 
101: === PAGE 10 ===
102: The pitch is addressed to a hypothetical management team. You submit the slides; there is no separate written business report.
103: The reference platform for the project will be announced; the choice of platform does not affect grading.
104: AI use: say where it helped, and check what it produced. Free assistants may use your conversations to improve their models, depending
105: on the provider and settings: never paste confidential or personal data.
```

### 原始第860–902行

```text
860: # Style and format
861: {tone}. {length}. {structure, e.g., bullet points, a table, a fixed template}.
862: # Examples
863: <example> {a typical request and an ideal answer} </example>
864: 36
865: 
866: === PAGE 68 ===
867: The template for the Rapide SA exercise (Session 2) and for your project.
868: Each section answers a new employee’s question: who am I, what is my goal, what is not my job, where do I find information, what should
869: the result look like, can you show me one?
870: Scope and Knowledge are where most applications fail: decide what happens with a question the assistant should not, or cannot, answer.
871: Speaker notes
872: 
873: === PAGE 69 ===
874: Test, Diagnose, Refine
875: Write 5–10 test questions first: typical requests, edge cases, out-of-scope requests.
876: Keep a few aside for the final check.
877: Change one thing at a time; rerun the same questions; compare.
878: Keep a revision log:
879: Version
880: Change
881: Why
882: Test questions OK
883: v0
884: First draft
885: -
886: 4/8
887: v1
888: Added scope + fallback
889: Answered off-topic requests
890: 6/8
891: v2
892: Added two examples
893: Inconsistent format
894: 7/8
895: 37
896: 
897: === PAGE 70 ===
898: The table is an illustration.
899: The revision log is raw material for your technical report: it documents your design decisions and the evidence behind them.
900: Rerun each question more than once: if answers are sampled, one good answer proves little.
901: The questions you tune on tell you how well you tuned. The ones you kept aside tell you how the assistant will do on new cases.
902: Practise the whole loop in the Rapide SA exercise (Session 2).
```

### 原始第1031–1121行

```text
1031: === PAGE 82 ===
1032: Project Requirements
1033: Each application must:
1034: address a clearly defined business problem
1035: for a precise user segment;
1036: have configurable instructions;
1037: use business-specific knowledge (context
1038: injection or RAG);
1039: include at least one meaningful tool or action;
1040: be shareable for testing and evaluation.
1041: Be ready to answer:
1042: Why is a standard chatbot not
1043: enough?
1044: What is your information advantage?
1045: What is your barrier to entry?
1046: Who pays, and why?
1047: Data: public, synthetic, or appropriately authorized only. A long prompt or a generic
1048: chatbot is not enough.
1049: 43
1050: 
1051: === PAGE 83 ===
1052: A meaningful tool is one the use case needs - a calculation, a lookup, an action, typically an API call or code execution.
1053: Example directions: a regulatory assistant for entrepreneurs (Swiss regulations; deadline calculator); a due-diligence assistant for private
1054: investors (financial reports; scoring); a real-estate advisor for homeowners (cantonal tax rules; financial estimate); an ESG compliance
1055: assistant for exporting SMEs (ESG standards; compliance scoring).
1056: No real customer, employee, or patient records, and no confidential employer documents. Synthetic data is fine - generating it is a good
1057: use of an LLM.
1058: Answer the four questions now, even roughly; they are the backbone of the final pitch.
1059: Speaker notes
1060: 
1061: === PAGE 84 ===
1062: Project Kickoff
1063: Step
1064: Activity
1065: ~Time
1066: 1. Form groups
1067: Roles, a shared document for the canvas
1068: 5 min
1069: 2. Choose a
1070: problem
1071: Users, pain point; check the fit criteria
1072: 10 min
1073: 3. Project canvas
1074: Fill in the canvas (next slide)
1075: 10 min
1076: 4. Instructions
1077: Draft v0 system instructions from the template
1078: 7 min
1079: 5. First test
1080: Optional: three test questions in any assistant
1081: 3 min
1082: The priority is a well-defined problem and first instructions, not a working application.
1083: 44
1084: 
1085: === PAGE 85 ===
1086: Kickoff, 35 min.
1087: Common problems at this stage:
1088: too vague (“help students study”): define a precise user and a measurable pain point;
1089: no need for an LLM: go back to the claims-handling debrief - which part really needs generative AI?
1090: no knowledge source: find one concrete public or synthetic source before the next session.
1091: The canvas, the instructions, and a first prototype are refined after class.
1092: Speaker notes
1093: 
1094: === PAGE 86 ===
1095: Project Canvas
1096: Field
1097: Guiding question
1098: Users
1099: Who exactly, in which situation?
1100: Pain point
1101: What problem, measured how (time, cost, errors)?
1102: Current process
1103: How is it solved today, and by whom?
1104: Objectives
1105: What should it do - and explicitly not do?
1106: Knowledge
1107: Which documents or data? Public, synthetic, authorized?
1108: Tool or action
1109: Which calculation, lookup, or action makes it useful?
1110: Success metrics
1111: How will you know it works?
1112: Risks
1113: What happens when it is wrong? Who could misuse it?
1114: Why not a chatbot?
1115: Your answer to the strategic questions.
1116: 45
1117: 
1118: === PAGE 87 ===
1119: The canvas is the first draft of your report’s first section and of your pitch. It will change: keep its versions.
1120: Speaker notes
1121: 
```

## 原课件：planning_sources/Knowledge Integration  RAG_with_notes.txt

以下行号对应本地原始TXT文件；课件印刷页码以正文为准。

### 原始第699–750行

```text
699: === PAGE 46 ===
700: Evaluating a Knowledge Component
701: Dimension
702: Test
703: Evidence
704: Did the model receive the expected
705: passage(s)?
706: Groundedness
707: Is every claim supported by them?
708: Abstention
709: Does it decline when the evidence is
710: absent?
711: Answer
712: quality
713: Does it answer the question correctly?
714: 24
715: 
716: === PAGE 47 ===
717: A known-answer question is one where you know, before asking, which passage or passages contain the answer, or that none does.
718: It lets you check retrieval separately from generation.
719: This is the test set you start building in today’s project work.
720: How to check today:
721: evidence: is the expected passage among those the model received?
722: groundedness: check every claim against the cited passage;
723: abstention: ask questions the documents do not cover;
724: answer quality: compare with the expected answer.
725: A fifth, business dimension: cost and latency.
726: What did the architecture buy us? Compare time and tokens per answer, before and after a change.
727: Speaker notes
728: 
729: === PAGE 48 ===
730: Which Knowledge Architecture?
731: If…
732: Start with…
733: The corpus fits comfortably
734: Full context (with
735: caching)
736: Large, changing, access-
737: controlled
738: Retrieval
739: Exact identifiers matter
740: Hybrid retrieval
741: Tests expose a specific failure
742: The matching technique
743: Start simple; add complexity where testing shows that you
744: need it.
745: 25
746: 
747: === PAGE 49 ===
748: Read the table from the top: most applications should stop at one of the first rows.
749: Every added component costs development time, money per request, and something else that can fail.
750: Matching techniques, for the last row:
```

### 原始第769–794行

```text
769: === PAGE 52 ===
770: A Reference Platform: Mistral
771: Concept
772: Mistral
773: Instructions
774: Agent instructions
775: Knowledge
776: Libraries, or full context
777: Tools
778: Search, code, functions
779: Testing
780: Studio, Conversations API
781: The reference, not a requirement.
782: Managed systems hide some choices: test what you can
783: observe.
784: 27
785: 
786: === PAGE 53 ===
787: We demonstrate with Mistral Studio. You may use any platform that meets the project requirements: the platform is not the learning
788: objective.
789: On another platform, identify the same elements: where the instructions are, how knowledge is added, which tools exist, and how
790: you can test and inspect the behaviour.
791: Full mapping:
792: model → the Agent’s model;
793: instructions → the Agent’s instructions;
794: knowledge → Libraries (managed retrieval), or the documents pasted into the instructions;
```

### 原始第890–1008行

```text
890: with context injection, it means the material you provided was incomplete, or the context was badly built;
891: evidence that was present but misused is a generation failure.
892: Then apply the same workflow to your own project.
893: Speaker notes
894: 02_rapide_sa.md
895: open in Colab
896: 
897: === PAGE 58 ===
898: Project: The Knowledge Component
899: Milestone: a working knowledge component, and its limits.
900: 1. Choose authoritative sources, and a small corpus.
901: 2. Choose the architecture: full context or retrieval? Justify it.
902: 3. Integrate the knowledge.
903: 4. Document what you can observe, and what remains
904: unknown.
905: 30
906: 
907: === PAGE 59 ===
908: Start from the documents identified in your Session 1 canvas.
909: The session is for integrating, testing, diagnosing, and improving, not for browsing the web for PDFs.
910: Identify the authoritative sources your application needs.
911: Use public, synthetic, or authorized documents only, and keep gathering and cleaning them short.
912: Keep the corpus small enough to know what is in it: you need to know where each answer is, to test retrieval.
913: Update your system instructions from Session 1: what to do when the documents do not answer, and how to cite.
914: Record what the platform does: what is observable, what is unknown, and the equivalent architecture in the course’s terms.
915: If it exposes settings (chunking, metadata, number of passages, retrieval mode, citations), note them.
916: “Unknown” is an acceptable answer for an opaque platform, as long as you say so and test accordingly: if you cannot see what was
917: retrieved, check whether the answer cites the right passage.
918: Reference platform: Mistral Studio + Libraries; any platform that meets the requirements is fine.
919: If yours hides how retrieval works, say what you can observe and what remains unknown, test the behaviour rather than assuming
920: how it works, and describe the equivalent architecture (context injection, retrieval, hybrid).
921: With Mistral:
922: build or refine the Agent in Studio;
923: either put the documents into the instructions, or create a Library, upload your documents, and attach it (in Studio, or with the starter
924: notebook);
925: test known-answer and absent-answer questions;
926: check the sources and tools used;
927: optionally, use the notebook to inspect the extracted text or compare two knowledge configurations.
928: Speaker notes
929: 
930: === PAGE 60 ===
931: Test, Diagnose, Improve
932: Block 4: build 8–10 known-answer questions. Know the
933: expected evidence before you ask.
934: Include
935: one and several
936: passages;
937: exact code,
938: paraphrase;
939: absent or
940: conflicting
941: evidence.
942: Diagnose
943: Evidence
944: available?
945: Used correctly,
946: and cited?
947: Abstained when
948: needed?
949: Improve
950: Find ≥ 1 failure.
951: Change one thing.
952: Log change →
953: reason → result.
954: 31
955: 
956: === PAGE 61 ===
957: You are not trying to show that your knowledge system works: find at least one way in which it fails.
958: For each question, record the expected evidence (one or more passages), or mark that the answer should be absent.
959: Mix:
960: an answer in one passage;
961: an answer needing two passages;
962: an exact name, code, or acronym;
963: a paraphrase of the document’s wording;
964: an answer absent from the corpus;
965: outdated or conflicting sources, if any.
966: For each question:
967: Was the right evidence retrieved or provided?
968: Did the model use it, and cite it?
969: Did it abstain when evidence was absent?
970: If wrong: was the evidence missing, or present but misused?
971: Make at least one improvement, and log what changed, why, and the result.
972: Use the revision log from Session 1: version, change, reason, result.
973: Keep two or three questions aside, and run them only at the end.
974: Results on questions you tuned on overstate the quality on new questions.
975: The test set, the diagnosis, and the log are raw material for the implementation and evaluation sections of your technical report.
976: Speaker notes
977: 
978: === PAGE 62 ===
979: Before Session 3
980: Each group has:
981: its project canvas completed (Session 1, “Project Canvas”
982: slide);
983: its knowledge sources, and a working first integration;
984: a short justification: context injection or retrieval, and why;
985: a known-answer test set, with at least one diagnosed
986: failure;
987: an updated revision log;
988: a list of improvements to make.
989: 32
990: 
991: === PAGE 63 ===
992: The canvas is the first draft of your report’s first section and of your pitch.
993: Its fields: users, pain point, current process, objectives, knowledge, tool or action, success metrics, risks, why not a chatbot.
994: Session 3 adds tools and actions.
995: Think about which questions in your test set the documents cannot answer, but a tool could (a calculation, a lookup in a live system).
996: Speaker notes
997: 
998: === PAGE 64 ===
```

## 原课件：planning_sources/Tools, APIs  Agentic AI.txt

以下行号对应本地原始TXT文件；课件印刷页码以正文为准。

### 原始第283–296行

```text
283: === PAGE 13 ===
284: Project: Add a Tool
285: Milestone: at least one meaningful tool or action in your application.
286: 1. Find the need: a question in your test set that documents cannot answer (live data, a
287: calculation, an action).
288: 2. Choose: a custom function (start from the ECB notebook), or a provider tool (search,
289: code) if a test question needs one.
290: 3. Describe it: purpose, inputs, outputs, limits.
291: 4. Test: called when needed? Not called when not? Failures handled?
292: Meaningful means a capability your application needs: enabling search or code is not, by
293: itself, an improvement. Programming is not a prerequisite: an LLM can draft the function;
294: you must understand what it does.
295: 13
```

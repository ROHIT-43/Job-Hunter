#!/usr/bin/env python3
"""gen_resumes.py — generate per-company tailored resume.tex files.

Each resume = the TRUTHFUL master content (verbatim experience/projects/education/
achievements bullets from data/resume/resume-builder.tex) + a per-role Technical
Skills section and role subtitle. We only re-order/relabel skills and shift the
subtitle to mirror the JD — we never rewrite bullets or invent experience.

Hard rule (see memory arnab-resume-facts): Java is native-Android only; it lives
in the Languages line and the Android SDK bullet, NEVER as a backend skill.
Backend is described architecturally (microservices/distributed/event-driven).
"""
import os

HEADER = r"""\documentclass[]{resume-openfont}
\usepackage{xcolor}

\pagestyle{fancy}
\resetHeaderAndFooter

\newcommand{\resumeHeading}[4]{\runsubsection{\uppercase{#1}}\descript{ | #2}\hfill\location{#4}\fakeNewLine}
\newcommand{\educationHeading}[4]{\runsubsection{#1}\hspace*{\fill}  \location{#4}\\
\descript{#2}\fakeNewLine}
\newcommand{\projectHeading}[3]{\Project{#1}{#2}
\descript{#3}\fakeNewLine}
\newcommand{\projectHeadingWithDate}[4]{\Project{#1}{#2}
\descript{#4}\fakeNewLine}
\newcommand{\courseWork}[1]{\textbf{Coursework:} #1}
\newcommand{\teacherAssistant}[1]{\textbf{Teacher Assistant (TA):} #1}

% TAILORED FOR: %%TITLE%%
% Truthful master bullets (unchanged); only Technical Skills + subtitle tailored.

\begin{document}

\begin{center}
	{\Huge \scshape \textbf{Arnab Dutta} }
    \\ \vspace{1pt}
    \small
     \href{mailto:arnabduttasocial@gmail.com}{\raisebox{-0.2\height}\faEnvelope\ \underline{arnabduttasocial@gmail.com}} ~
     \raisebox{-0.1\height}\faPhone\ +91-6289414754 ~
     \href{https://bytedex.github.io/}{\underline{bytedex.github.io}} ~
     \href{https://www.linkedin.com/in/arnab-dutta-1048/}{\raisebox{-0.2\height}\faLinkedin\ \underline{linkedin.com/in/arnab-dutta}} ~
     \href{https://github.com/bytedex}{\raisebox{-0.2\height}\faGithub\ \underline{github.com/bytedex}}
	\vspace{-8pt}
\end{center}
"""

# Truthful experience — verbatim from the master resume. Subtitle is the only
# tailored token (%%SUBTITLE%%). Java appears ONLY in the native-Android bullet.
EXPERIENCE = r"""
\section{Experience}
\resumeHeading{Juspay (Nammayatri)}{%%SUBTITLE%%}{Kolkata, India}{July 2023 -- Present}
\begin{bullets}
    \item Designed and built \textbf{Namma-DSL}, a code \textbf{data transformation} platform that auto-generates API definitions, type signatures, and service endpoints from YAML specs --- eliminating \textbf{50,000+} lines of handwritten code, reducing \textbf{enterprise} service onboarding time by \textbf{40\%}, and enabling \textbf{large-scale} \textbf{distributed} \textbf{multi-user} development across a \textbf{collaborative} platform serving millions of users.
    \item Architected a \textbf{multi-vendor emergency dispatch system} using \textbf{event-driven microservices architecture}, integrating \textbf{3 external APIs} with a plugin-based vendor abstraction and implementing a \textbf{real-time stream processing} pipeline with a \textbf{2-second GPS pulse} for SOS location tracking --- delivering \textbf{scalable, maintainable} solutions with \textbf{clean code} practices.
    \item Reduced \textbf{Redis} read latency by \textbf{65\%} on a \textbf{data aggregation} leaderboard via dual-key caching and time-partitioned keys, and optimized \textbf{native Android} mobile SDK event logging in \textbf{Java} with client-side batching and async routing to \textbf{Apache Kafka}, cutting network calls by \textbf{30--40\%}.
    \item Built an end-to-end \textbf{GitHub Actions CI/CD} pipeline (\textbf{Vitest + Playwright}) with \textbf{Kubernetes-based} deployment workflows and AI-powered test scaffolders, and deployed \textbf{MCP servers} for \textbf{agentic / LLM} workflows --- contributing to a culture of \textbf{code reviews} and \textbf{design reviews} across \textbf{12+ microservices}.
    \item Led a \textbf{cross-functional} team of \textbf{6 engineers}, mentored \textbf{3 interns} in an \textbf{agile} environment, and shipped ambulance dispatch, real-time bus tracking, and FRFS ticketing for Yatri Sathi --- delivering features meeting \textbf{business and product goals}.
\end{bullets}
\sectionsep

\resumeHeading{Yellow AI}{Solutions Engineer (Contract)}{Bangalore, India}{May 2023 -- June 2023}
\begin{bullets}
    \item Designed and deployed \textbf{10+} \textbf{enterprise} chatbot solutions using \textbf{TypeScript} for \textbf{5+ clients}, collaborating within a \textbf{cross-functional team} to deliver features meeting business goals.
    \item Automated \textbf{LLM} intent deduplication via Puppeteer, reducing conflicts from \textbf{98\% to 24\%} and improving generative AI response accuracy.
\end{bullets}
\sectionsep
"""

PROJECTS = r"""
\section{Projects}
\projectHeading{BlockchainDB}{https://github.com/bytedex/blockchaindb}{MongoDB, Express, Node}
\begin{bullets}
    \item Built a \textbf{distributed} backend for a JSON/MongoDB \textbf{database} on Blockchain (OrbitDB), with full CRUD, \textbf{data aggregation}, and RESTful API endpoints.
\end{bullets}
\sectionsep
"""

TAIL = r"""
\section{Education}
\educationHeading{Jalpaiguri Government Engineering College}{BTech, Computer Science \& Engineering, CGPA -- 8.91}{Jalpaiguri, West Bengal}{2019 -- 2023}
\courseWork{Data Structures \& Algorithms, Database Management Systems, Operating Systems, Computer Networks}
\sectionsep
\sectionsep

\section{Achievements}
\begin{bullets}
    \item \textbf{2000+} problems solved (\textbf{data structures and algorithms}) $|$ LeetCode \textbf{1800+} $|$ Codeforces \textbf{Expert (1622)} $|$ CodeChef \textbf{5-Star (2045)}
    \item \textbf{Gold Medalist} at International Olympiad of Mathematics (iOM) --- State Rank 1, National Rank 14
\end{bullets}
\sectionsep

\section{Technical Skills}
\begin{flushleft}
%%SKILLS%%
\end{flushleft}

\end{document}
"""


def skills(rows):
    return "\n    \\\\\n".join(f"    \\singleItem{{{lbl}: }}{{{val}}}" for lbl, val in rows)


# Per-company: folder, JD title, role subtitle, tailored (truthful) skills rows.
LANG_BACKEND = "Java, Python, TypeScript, JavaScript, Rust, C++, SQL"  # Java = language he knows (Android)
COMMON_CLOUD = ("Cloud \\& DevOps", "AWS (EKS), Kubernetes, Docker, CI/CD, GitHub Actions, Prometheus, Grafana")
COMMON_DB = ("Databases", "PostgreSQL, MySQL, Redis, MongoDB")

COMPANIES = {
 "01_Amazon": ("SDE II, EU GIL Installments (Amazon)", "Software Developer, Backend", [
    ("Languages", LANG_BACKEND),
    ("Distributed Systems \\& Scale", "Multi-tier distributed services, High-performance \\& reliable systems, System design, Performance optimization"),
    ("Event-Driven \\& Streaming", "Apache Kafka, Real-time stream processing, Event-driven microservices"),
    ("Backend \\& APIs", "Microservices architecture, RESTful APIs, Web services, Data transformation pipelines"),
    COMMON_CLOUD, COMMON_DB]),
 "02_Amazon_Devices_India": ("SDE 2 (Amazon Devices India)", "Software Developer, Full Stack", [
    ("Languages", LANG_BACKEND),
    ("Backend \\& Distributed Systems", "Microservices, RESTful APIs, Event-driven architecture, High-scale distributed systems"),
    ("Frontend", "React, TypeScript, JavaScript, Responsive design"),
    ("AI / LLM", "LLM integration, Agentic workflows, MCP servers"),
    COMMON_CLOUD,
    ("Databases", "PostgreSQL, MySQL, Redis, MongoDB, DynamoDB")]),
 "04_Tata_Consultancy_Services": ("Java Developer (TCS)", "Software Developer, Backend", [
    ("Languages", LANG_BACKEND),
    ("APIs \\& Services", "RESTful APIs, Microservices architecture, API design \\& testing"),
    ("Databases", "PostgreSQL, MySQL (relational), Redis, MongoDB"),
    ("Quality \\& SDLC", "Debugging \\& troubleshooting, Unit/integration testing, Code reviews, Git"),
    ("Event-Driven \\& Streaming", "Apache Kafka, Real-time stream processing"),
    COMMON_CLOUD]),
 "06_Infosys": ("Fullstack (React+Python) Developer (Infosys)", "Software Developer, Full Stack", [
    ("Frontend", "ReactJS, TypeScript, JavaScript, Responsive design, Reusable components, HTML5, CSS3"),
    ("Backend", "Python, RESTful APIs, Microservices architecture, Event-driven services"),
    ("Practices", "Testing (unit/integration), Debugging, Version control (Git), Code reviews"),
    ("AI Enablement", "LLM integration, Agentic workflows, MCP servers, AI test scaffolders"),
    COMMON_CLOUD, COMMON_DB]),
 "08_NTT_DATA_Inc": ("Software Engineer Testing (NTT DATA)", "Software Developer, Backend \\& Test Automation", [
    ("Test Automation", "Playwright, Vitest, Test plans \\& cases, Regression \\& exploratory testing, AI test scaffolders"),
    ("CI/CD \\& DevOps", "GitHub Actions, Continuous Integration/Delivery, Kubernetes, Docker, Agile/Scrum"),
    ("Languages", LANG_BACKEND + " (OOP)"),
    ("Quality \\& Process", "SDLC, Code reviews, Debugging, Root-cause analysis"),
    ("Backend \\& Data", "RESTful APIs, Microservices, PostgreSQL, MySQL, Redis, MongoDB")]),
 "14_HARMAN_India": ("Software Engineer - Java SDET (HARMAN)", "Software Developer, Backend \\& Test Automation", [
    ("Languages", LANG_BACKEND + " (OOP)"),
    ("Test Automation", "Playwright, Vitest, Test frameworks, AI test scaffolders, Regression testing"),
    ("CI/CD \\& DevOps", "GitHub Actions, CI/CD pipelines, Docker, Kubernetes, AWS (EKS), Agile/Scrum"),
    ("Quality \\& Process", "SDLC, Code reviews, Debugging, Defect triage"),
    ("Backend \\& Data", "RESTful APIs, Microservices, Apache Kafka, PostgreSQL, MySQL, MongoDB")]),
 "15_Moody_s_Corporation": ("Software Engineer - Python Full Stack (Moody's)", "Software Developer, Full Stack", [
    ("Backend", "Python, RESTful APIs, Microservices, AWS Lambda / serverless concepts, Data pipelines"),
    ("Frontend", "React, TypeScript, JavaScript, Responsive design, HTML5, CSS3"),
    ("Cloud \\& DevOps", "AWS (EKS, S3, Lambda), Docker, CI/CD, GitHub Actions, Infrastructure-as-code"),
    ("Testing", "Unit \\& integration tests, Pytest-style frameworks, Vitest, Playwright"),
    ("AI / LLM", "LLM integration, Agentic \\& AI-assisted dev workflows, MCP servers"),
    COMMON_DB]),
 "17_Verint_Financial_Compliance": ("Software Engineer, Frontend (Verint Financial Compliance)", "Software Developer, Frontend", [
    ("Frontend", "ReactJS (functional components), TypeScript, JavaScript (ES6+), HTML5, CSS3, Redux / Context API, NPM"),
    ("Web", "REST-based web services, Responsive design, Cross-browser compatibility, Browser dev tools"),
    ("Quality", "TDD / BDD, Design \\& code reviews, Unit/integration testing (Vitest, Playwright)"),
    ("Languages", LANG_BACKEND),
    COMMON_CLOUD]),
 "18_Verint": ("Software Engineer, Frontend (Verint)", "Software Developer, Frontend", [
    ("Frontend", "ReactJS (functional components), TypeScript, JavaScript (ES6+), HTML5, CSS3, Redux / Context API, NPM"),
    ("Web", "REST-based web services, Responsive design, Cross-browser compatibility, Browser dev tools"),
    ("Quality", "TDD / BDD, Design \\& code reviews, Unit/integration testing (Vitest, Playwright)"),
    ("Languages", LANG_BACKEND),
    COMMON_CLOUD]),
}

base = "data/output/applications"
for folder, (title, subtitle, rows) in COMPANIES.items():
    doc = (HEADER.replace("%%TITLE%%", title)
           + EXPERIENCE.replace("%%SUBTITLE%%", subtitle)
           + PROJECTS
           + TAIL.replace("%%SKILLS%%", skills(rows)))
    path = os.path.join(base, folder, "resume.tex")
    with open(path, "w") as f:
        f.write(doc)
    print(f"wrote {path}")

**NAME: PRIYANSHU KRIPASHANKAR SINGH
ROLL NO:BM24BTECH11020
Application** **EMAIL: bm24btech11020@iith.ac.in
IIT HYDERABAD/BIOMEDICAL ENGINEERING.**

# WORK LOG

## Intern Selection Task – I’M BESIDE YOU

# Day 1 – Understanding the Problem and the Data

I started the task by first trying to understand what the company was actually asking me to do. I decided not to start coding immediately because the dataset was large and I felt that if I misunderstood the problem at the beginning, I could end up building the wrong solution.
The timing of this task was also a little difficult for me. The past 10 days had already been quite hectic because I was balancing regular classes with multiple exams, presentations, and Smart India Hackathon (SIH) work with my team. SIH also had a strict deadline, so a good amount of my time was going into discussions, development and preparation with the team. Because of this, I had to work on this task in the time slots I could find rather than treating the whole week as completely free.
I mention this because it affected one of my biggest decisions later: I knew I had to spend enough time understanding the problem properly, but I also had to make sure that the final solution was realistic for the time I actually had.

## Reading the documentation first

I started with the README.md and data\_schema.md files.
I read both of them once, but I still had a lot of doubts. So I went through them again and then a third time while looking at actual records from the dataset. I wanted to understand what each level of the data meant before deciding how I would process it.
There were two datasets:

* Dataset A — around 63 sessions and roughly 162,000 events, with ground truth.
* Dataset B — around 15 sessions and roughly 20,000 events, without ground truth.
My first impression was that Dataset A was basically the labelled dataset and Dataset B was the unlabelled/test dataset. So initially I was thinking about the problem almost like a normal machine-learning classification problem.
But after reading the documentation more carefully, I realised that this was not really the right way to think about it.

## Understanding what an event actually means

One of my first doubts was the meaning of an event.
Because there are so many events in the dataset, I initially thought an event might represent a meaningful user action or perhaps even a complete task.
After looking at the schema and actual records, I understood that an event is much smaller. It is basically one low-level recorded operation such as a keystroke, click, application switch, browser event, clipboard event, screenshot event, etc.
That meant a real piece of work could contain hundreds of individual events.
For example, suppose someone has to register an employee. They may open a website, move to a page, enter a name, copy an ID, paste something into another application, submit a form and then check the result.
From a human point of view, I would call that one piece of work.
But in the logs, all of those actions may appear as many separate events.
This led to one of the first important conclusions I made:
An event is not the same thing as a work unit.
I needed to find a way to move from many small events to a meaningful piece of work.
The final terminology I settled on was:
Event → Activity → Process execution / work unit → Workflow / process type → Segment.
In simple terms, I thought of an activity as a useful grouping of low-level events, a process execution as one actual instance of some work, and a workflow/process type as the repeated kind of work that those executions belong to. A segment is then the time interval I finally write to the required output file.
This distinction became very important later.

## My first mistake: assuming chunks were tasks

Another thing I misunderstood at the beginning was the meaning of a chunk.
Since the recordings are divided into chunks, I initially thought a chunk might correspond to one task or at least one meaningful piece of business work.
After thinking about the way the data was recorded, I realised that this was wrong.
A chunk is simply a fixed recording bucket. It is not a business-process boundary. One task can continue from one chunk into the next, and different pieces of work can also occur inside the same session. The final solution document makes this distinction very explicit: a session is one continuous recording, while chunks are only recording buckets.
This changed my understanding quite a lot.
I had originally been thinking:
“Maybe I can find the task inside each chunk.”
I then realised that I actually needed to think about the whole session as one timeline and ignore chunk boundaries when deciding what work belongs together.
This was one of the first major assumptions I had to correct.

## The problem was more than just finding time gaps

At this point I started asking myself a more important question:
What exactly am I trying to recover from the logs?
Initially, I was thinking that I mainly needed to find where one task ended and another started.
But after looking at the problem more carefully, I realised that this was still not quite enough.
Different business processes can be happening in an interleaved way.
For example, the activity order could look like:
A1 → B1 → A2 → C1 → B2 → A3
So the activities of Process A are not necessarily next to each other in the raw timeline.
This means I cannot simply split the timeline whenever there is a time gap and call each part one task.
The real question became:
Which activities belong to the same actual piece of work?
The solution document describes this as a latent process-assignment problem — basically, I need to decide which process execution each activity belongs to, while also allowing for activity that is unrelated or not yet understood.
That became the main idea behind the solution.

## Using AI after doing my own reading

At this point I still had several doubts, so I started using AI tools to help me understand the problem better.
I deliberately did not start by pasting the whole task into an AI and asking for a solution.
I first read the documentation myself several times and looked at the data.
Only after I had my own understanding did I start discussing specific doubts with ChatGPT.
I mainly used it to challenge my interpretation and explain concepts that were still unclear to me.
For example, I discussed questions like:

* What exactly is an event?
* How is an event different from a work unit?
* Why are chunks not task boundaries?
* Is this actually a classification problem?
* How should Dataset A and Dataset B be used?
* What would a reasonable segmentation approach look like?
* What mistakes could I be making in my current interpretation?
I also watched a few YouTube videos about analysing JSON and JSONL data, mainly to get more comfortable with exploring large log files and understanding how people usually inspect things such as timestamps, event types, sessions and repeated patterns before modelling.
The important part for me was that I used these tools after forming my own understanding, rather than replacing my own analysis with an AI-generated answer.

## My first rough solution idea

After this, I started writing down a rough solution in my own words.
My first basic idea was:
Raw logs → understand events → find work units → group repeated work → find automation opportunities.
But even this simple plan raised a lot of questions.
How do I decide that two activities belong to the same work?
I could use time.
I could use the application.
I could use text.
I could look at what action happened before and after.
But none of these is reliable on its own.
For example:

* A large time gap does not always mean a new task.
* Changing applications does not always mean a new task.
* Similar text does not always mean the same process.
* The same process can be performed through slightly different paths.
So even by the end of Day 1, I was already moving away from a simple “time-based segmentation” idea.

## Another important issue: not everything is business work

I also realised that the logs contain activity that may not actually belong to a business process.
If I force every single activity into some business process, I could accidentally make one process look much longer than it really is.
For example, unrelated browsing, idle activity, system/recording activity or other unrelated actions could appear in the middle of a genuine business task.
So I decided that the system would need explicit internal states for:
Process A / Process B / ... / UNASSIGNED / UNKNOWN
where UNASSIGNED means there is evidence that the activity is not part of the business process being reconstructed, while UNKNOWN means the activity might be business-related but there is not enough evidence yet to assign it confidently.
This was important because I did not want to make the solution look cleaner by forcing uncertain data into a process.

## Problems I faced on Day 1

The first day was mostly about correcting my own understanding.
The main problems were:

1. I initially misunderstood what an event represented.  
I was thinking about events at too high a level. I later understood that they are low-level recorded operations.
2. I initially thought chunks might represent tasks.  
I later realised they are only recording buckets.
3. I initially thought this was a normal labelled/unlabelled classification setup.  
I later realised that the main problem is recovering actual process executions from low-level activity.
4. I initially focused too much on boundaries.  
Later I realised that I first need to determine which activities belong to the same process, and only then convert those executions into the required time segments.
5. I realised that not every activity should be forced into a business process.  
This led to the idea of explicit UNASSIGNED and UNKNOWN states.
6. The amount of data was much larger than something I could inspect manually.  
With around 162,000 events in Dataset A alone, I knew I needed a structured and measurable approach.

## End of Day 1

By the end of Day 1, I had not written the final solution yet, but I had a much better understanding of what I was actually trying to solve.
My mental model at that point was:
I have a stream of low-level desktop events. I need to turn them into useful activities, figure out which activities belong to the same business process execution, and then use those recovered executions to understand recurring workflows and possible automation opportunities.
That became the starting point for Day 2.

# Day 2 – Designing and Finalizing the Solution

On Day 2, I moved from understanding the problem to deciding exactly how I wanted to solve it.
The time constraint was becoming important at this stage. The whole previous 10-day period had already been busy because of SIH, exams, classes and presentations. Because of that, I knew I could not spend the rest of the task experimenting without a clear direction.
After accounting for the available time, I realised that I effectively had about four days for implementation once the planning phase was complete.
So I wanted the solution to be ambitious enough to solve the real problem, but still realistic enough to finish.

## I first designed a rough solution myself

Before asking ChatGPT or Claude for anything, I wrote a rough architecture on my own based on what I had understood from the previous day.
The first version was roughly:
Raw event logs
→ normalize the data
→ convert low-level events into activities
→ find relationships between activities
→ recover process executions
→ group similar executions into workflow types
→ analyse Dataset B
→ find good automation candidates
→ build one prototype
Writing this down helped me notice that there were actually several different problems mixed together.
I was not just doing “segmentation.”
I was doing:
event processing → activity extraction → process recovery → workflow discovery → automation analysis.
That made the problem much clearer.

## I discussed my architecture with ChatGPT critically

After I had my own rough architecture, I took it to ChatGPT.
This time I was not asking it to generate the solution for me.
I specifically asked it to criticise my plan.
I asked questions such as:

* Am I making any major invalid assumption?
* Am I treating the data too cleanly?
* Am I assuming that process activity will always be contiguous?
* Am I relying too much on time gaps?
* Am I relying too much on application names?
* Am I assuming that the text information is always available?
* Could my approach work on Dataset B, where the applications are different?
* Am I accidentally building something that works on Dataset A but would fail on B?
* Am I overengineering the problem?
* Can I realistically implement all of this in the time remaining?
This discussion helped me catch several weaknesses.
One important change was that I stopped thinking of time gaps as hard task boundaries.
Another was that I started thinking in terms of relationships between activities instead.
For example, if two activities involve the same employee ID, case ID, document or other entity, that could be much stronger evidence that they belong to the same work than simply being close in time.
Likewise, an explicit triggered\_by relationship could be very strong evidence.
On the other hand, merely being in the same application or having similar text is weaker evidence.
This eventually became an explicit evidence hierarchy in my final solution:
Strong evidence: same entity/case/document, direct relationship, triggered-by.
Moderate evidence: compatible application/context and repeated structural patterns.
Weak evidence: time proximity and semantic similarity alone.
I liked this idea and added it to my solution document.

## Building the first real version of solution.md

After that discussion, I started writing a more complete solution.md.
The main principle I ended up using was:
Recover the work first. Analyze the recovered work second. Choose automation third. Build the prototype last.
This helped me avoid jumping directly into automation before understanding what the actual work patterns were.
The solution was divided into stages.
First, I would understand and normalize the raw logs.
Then I would convert low-level events into a smaller set of useful activities.
Then I would use relationships between activities to recover process executions.
Then I would group similar process executions into workflow/process types.
Only after that would I move to Dataset B and analyse which workflows were recurring and suitable for automation.

## A major design decision: separate execution recovery from final segments

One issue I spent quite a bit of time thinking about was the difference between a process execution and a segment.
Suppose a process starts, gets interrupted by another process, and later continues.
Internally, I still want to treat that as one logical execution if the evidence supports it.
But the required segments.jsonl output needs normal contiguous start and end intervals.
So I decided on an explicit conversion:
Recovered execution
→ split it into maximal contiguous runs
→ write one output segment for each run
→ give all those segments the same process label.
This solved an important mismatch between the way I needed to reason about the work internally and the format required by the task.
I also decided that I should not randomly choose one “magic” time gap for interruptions.
Instead, I would test a few reasonable tolerances on Dataset A and choose one based on actual boundary performance.

## Deciding to build the output and validator early

Another decision I made after reviewing the problem was to create the output system early instead of leaving it until the end.
I planned to have:

* a segments.jsonl writer,
* a validator,
* and initially a simple placeholder segmenter.
The placeholder would just produce a basic segment so that I could verify that the complete pipeline could generate a valid output file before spending time on better segmentation.
The reason was simple:
I did not want to spend all my time building an advanced method and then realise at the end that the actual output format or validation was wrong.
So the idea was:
First make sure the whole pipeline can produce a valid submission. Then keep improving the part that decides the segments.

## Handling Dataset A and Dataset B differently

Another important decision came from thinking about how my method would transfer from A to B.
Dataset B comes from different departments and different applications.
That means I cannot make my system depend on things that are specific to Dataset A.
For example, I should not make rules such as:
active\_app == "Chrome" means something specific.
or:
this particular URL means this particular process.
or:
this exact vocabulary belongs to Process X.
That might work well on Dataset A but fail completely on Dataset B.
So I decided to use relationships rather than memorised identities.
Things like:

* same application,
* same browser tab,
* similar window,
* same entity,
* similarity between two pieces of text,
* action-transition patterns,
are acceptable because they describe relationships rather than depending on one specific application or website.
Also, I decided that Dataset A's process names should not simply be copied to Dataset B. B has to be treated as a new workflow-discovery problem.
I considered this an important check against overfitting my solution to Dataset A.

## Deciding what an activity should look like

Another part of the plan I added was to convert the raw events into a small and simple activity vocabulary.
Instead of working with hundreds of low-level event details directly, I wanted a smaller set such as:

* TEXT\_ENTRY
* CLICK
* NAVIGATE
* COPY
* PASTE
* APP\_SWITCH
* SCROLL
* DIALOG
* SHORTCUT
* OTHER
The important point was that I did not want to spend half the available time building a perfect activity taxonomy.
The goal was only to create a representation that gives the relationship model useful information while still allowing me to trace each activity back to the original raw events.
I also noted that text\_input\_complete should not be trusted blindly because it is not always complete or clean. Where necessary, text could be reconstructed from keystrokes, clipboard information and surrounding context.

## Reconstructing ground truth properly

Another part of my final plan was to use Dataset A properly rather than simply looking at the labels.
I planned to reconstruct the actual process executions from gt.jsonl and gt\_manifest.json.
I also noticed that the ground truth itself has some quirks. For example, consecutive duplicate process\_started events can appear, and some starts do not always have a clean matching switch-out event.
So I decided that I should reconstruct the ground truth defensively and compare the two ground-truth sources rather than blindly trusting one file.
This gave me a proper reference against which I could test my own process recovery method.

## Quantitative evaluation instead of only looking at examples

Another important decision was that I did not want to judge the segmentation only by looking at a few examples.
Dataset A has ground truth, so I can actually measure performance.
The first two metrics I planned to use were:
Boundary Precision / Recall / F1
and
Pairwise same-process F1.
For boundary matching, I planned to test several tolerances such as:
±0.5 s, ±1 s, ±2 s and ±5 s.
This made more sense to me than expecting every predicted timestamp to exactly match a ground-truth timestamp down to the millisecond.
I also decided that any train/test split for a learned model should be by session, not by randomly splitting events, because events from the same recording could otherwise end up on both sides and give an unrealistic result.

## Rule-based baseline before machine learning

I also discussed the question of whether I should immediately use a complex ML model.
I decided not to.
My final plan was to first build a transparent rule-based scoring system.
The basic idea was to give positive evidence to things like:

* same entity,
* triggered\_by,
* same window/context,
* same application,
and use things like a large time gap as weaker negative evidence.
The important thing was that the weights would be measured and tuned against Dataset A instead of being completely arbitrary.
After that, a supervised model such as logistic regression could be added if time allowed.
This gave me a much safer path because even if I ran out of time, I would still have a complete, explainable system.

## Deciding against a GNN

During the planning process I also considered whether an event graph and a GNN would be a good solution.
The graph representation itself still made sense to me because relationships between activities are important.
But I decided not to build a GNN.
The main reasons were:

* only around 63 labelled sessions in Dataset A,
* limited time,
* Dataset B coming from different departments and applications,
* more difficult validation,
* and the fact that the task is also testing practical judgment and business value, not just model complexity.
So I kept the graph as a conceptual way of representing relationships, but I planned to use a normal table/dataframe for the first version rather than building a heavy graph-learning system.
This was one of the places where I deliberately chose a simpler solution because of the deadline.

## Thinking about how to recover process executions

The relationship-based approach then became the main part of the segmentation plan.
For each pair of activities, I wanted to look at evidence such as:
Time: how far apart they are.
Application/context: same application, window, browser tab, etc.
Entity/object: same employee, document, invoice, case ID, file, etc.
Causal relationship: whether one action directly triggered another.
Semantic information: similarity in available text or screen context.
Workflow structure: whether certain actions repeatedly appear together or follow one another.
I also realised that I should not compare every activity against every other activity because that would become unnecessarily expensive at this scale.
So I planned to first generate only reasonable candidate pairs — for example, nearby activities, activities sharing an entity, or activities connected through an explicit relationship — and score those pairs instead.
I also explicitly avoided simple connected-components clustering because a chain of strong relationships could accidentally merge two unrelated processes.
Instead, the recovered path should also respect things like time ordering, entity continuity and process continuity.

## Clustering recovered executions into workflows

Once process executions are recovered, I still need to answer:
What kind of process is this?
I decided that this should be done after execution recovery rather than directly clustering raw events.
The hierarchy I settled on was:
Events → Process executions → Workflow/process types → Variants.
For each execution, I planned to create a compact signature using things like:

* the activity sequence,
* application-transition structure,
* generic entity/action pattern,
* duration,
* activity count,
* and optionally some text similarity.
I chose agglomerative clustering as the first method because I do not know in advance how many process types exist, and it was easier to explain than forcing a fixed number of clusters.
I also planned to inspect the clusters instead of blindly assuming that every cluster automatically represents one business process.

## Using AI for naming the discovered workflows

There was also one direct use of an LLM in the final plan.
Some representative screen/window text may be in Japanese, so once clusters were formed, I planned to use an LLM to help translate representative Japanese text and give the clusters meaningful human-readable labels.
This was not meant to make the model decide which events belong together.
The actual grouping would come from my process-discovery method.
The LLM would only help make the resulting labels understandable.
I also explicitly planned to record this GenAI usage in the work log because it is part of the task requirements.

## Moving from Dataset A to Dataset B

After validating the process recovery approach on Dataset A, the next step in my plan was to apply the same general method to Dataset B.
The important difference was that I would discover B's workflow types from B itself rather than trying to force A's process names onto B.
After recovering executions in B, I planned to:

1. group similar executions,
2. identify the major workflow types,
3. look at variants inside each workflow,
4. build simple process/transition graphs,
5. measure how often each workflow occurs,
6. see how many sessions and people/machines are involved,
7. compare their recorded effort and application complexity,
8. and then identify which ones are reasonable automation candidates.
This made the final objective much clearer.
I was not just trying to produce segments.jsonl.
I was trying to recover useful information about how people actually perform work.

## How I planned to choose an automation candidate

At first, I naturally thought that the most frequent workflow would probably be the best one to automate.
But during the planning process I realised that frequency alone is not enough.
A process can be frequent but still require a lot of human judgment.
So I decided to evaluate automation candidates using several dimensions:
Impact  
How often does it happen, how much manual effort is involved, and how many people are affected?
Repeatability  
Is the workflow structurally consistent or highly variable?
Technical feasibility  
Are the inputs structured? Is the UI stable? Is there an API? How many decision branches are there?
Risk  
Could a mistake affect money, employee data, records, external communication, etc.?
Human judgment  
Does a person actually need to interpret or approve something?
This gave me a more sensible way to select the final prototype.

## The final prototype plan

For the final prototype, I deliberately decided not to make the scope too broad.
The plan was to choose one process with a narrow scope, get it working end-to-end on one or two example cases, and clearly explain what would need to be generalized later.
I would then choose the actual automation mechanism based on the workflow.
Depending on what the discovered process looked like, that could be:

* an API/rule-based workflow,
* browser automation/RPA,
* an AI-assisted step followed by deterministic actions,
* or a human-in-the-loop system if the process required approval.
This was another place where I deliberately kept the solution practical instead of deciding on a technology first and then trying to force the data into it.

## Reviewing the whole plan with Claude

After I had a fairly complete version of solution.md, I gave the document to Claude for another review.
This time I asked it to behave more like a reviewer and look for flaws in the plan.
I specifically asked it to check things such as:

* whether my assumptions were valid,
* whether the plan was too optimistic,
* whether I was overfitting to Dataset A,
* whether the execution/segment distinction made sense,
* whether I was using the ground truth correctly,
* whether the plan could realistically be implemented in the remaining time,
* and whether any part of the architecture was unnecessary.
Claude suggested several changes and raised some concerns.
I did not accept all of them.
Some suggestions improved the plan, so I added them.
Some suggestions added too much complexity or did not fit the actual task, so I rejected them.
Then I updated solution.md again.

## Repeating the review process

I went back and forth between the plan and the two AI reviewers several times.
The process was roughly:
My solution
→ discuss with ChatGPT
→ find weaknesses
→ update solution.md
→ give the updated document to Claude
→ find more issues
→ accept useful changes
→ reject unnecessary changes
→ update the document again
→ repeat.
I went through roughly 3–4 iterations of this.
The final version was therefore not a document that I simply copied from an AI.
The basic architecture came from my own understanding of the problem, and I used ChatGPT and Claude mainly to challenge the architecture, find hidden assumptions and point out things I had missed.
That distinction was important to me.

## The final time constraint and descoping decision

By the time I finished this planning stage, I had to make a practical decision about scope.
Because the past 10 days had already been busy with SIH, exams, classes and presentations, I had not been able to spend unlimited hours on this task.
At this point, I had roughly four days left for implementation, and two of those had effectively gone into understanding the problem and carefully building the solution plan.
So I decided that I could not afford to chase every possible improvement.
The final solution was therefore divided into levels:
T0 — mandatory work needed for a complete submission
T1 — useful improvements if time allows
T2 — stretch ideas that could be skipped without hurting the main submission.
This helped me stay realistic.
For example, the rule-based relationship scorer became the main baseline.
A supervised model was kept as an improvement.
A GNN was completely dropped from the plan under the current deadline.
Similarly, screenshot analysis was kept for ambiguous cases rather than making OCR or image processing the foundation of the entire system.
The general idea was:
Finish the complete T0 pipeline first. Improve it only after the full pipeline exists.
That became one of the main principles of my final plan.

## My final solution after Day 2

By the end of Day 2, the plan I had finalized was essentially:
Raw events
→ merge chunks into one session timeline
→ normalize the data
→ convert raw events into atomic activities
→ identify non-business activity where possible
→ find relationships between activities
→ recover process executions
→ validate them on Dataset A using ground truth
→ convert recovered executions into the required contiguous segments
→ cluster executions into workflow/process types
→ identify variants
→ apply the method to Dataset B
→ analyse recurring workflows
→ select an automation candidate using impact, repeatability, feasibility, risk and human judgment
→ build one focused automation prototype.
This final structure is what I wrote down in solution\_final\_v2(2).md. The document also deliberately keeps the phases in a T0/T1/T2 order so that I can stop at a sensible point if time becomes tight.

## Main lessons from Day 2

The biggest thing I learned on Day 2 was that the problem is not really about “finding time intervals.”
It is about trying to recover the actual work being performed from low-level computer activity.
A few decisions became especially important for me:

1. Recover work first, then create segments.  
The process execution is the important concept. The final segment is just the output representation.
2. Do not depend on time gaps alone.  
Time is evidence, not a complete definition of a task.
3. Strong relationships should matter more than weak similarity.  
For example, a shared entity can be much stronger evidence than two activities simply being close in time.
4. Do not force every activity into a workflow.  
UNASSIGNED and UNKNOWN are useful because real activity is messy.
5. Dataset A should be used for measurable validation.  
I should not rely only on visual examples when ground truth exists.
6. Dataset B must be treated as a new workflow-discovery problem.  
I should not simply copy A's labels or application-specific logic.
7. Keep the first solution simple and explainable.  
A working rule-based approach is more useful to me under the deadline than a half-finished complex model.
8. Use AI as a reviewer, not as a replacement for my own reasoning.  
The main value of ChatGPT and Claude was that they helped me question assumptions and improve the plan.
9. Keep the scope under control.  
Because of the overall academic workload and the limited implementation time, I had to make deliberate choices about what was essential and what could be postponed.

## End of Day 2

By the end of the second day, I felt that I had finally moved from “I understand what the task is asking” to “I know how I am going to solve it.”
The biggest change from my initial understanding was that I stopped thinking about the task as simple segmentation or classification.
Instead, I was now thinking about it as:
Recover the actual pieces of work → understand the recurring workflows → identify what is worth automating → build one practical prototype.
I had also finalized solution.md after several rounds of discussion and criticism with ChatGPT and Claude.
At that point, I deliberately stopped expanding the architecture.
I had a limited implementation window left, so my next focus was no longer planning. It was execution: build the T0 pipeline, measure it on Dataset A, learn from the failures, and then apply the refined approach to Dataset B.

# Day 3 – Moving from Experiments to a Working Pipeline

By the start of Day 3, I already had the basic activity layer working from the previous day. I had spent part of Day 2 building and checking activities.py, so I did not want to keep changing that layer while experimenting with the actual segmentation logic.
I had already seen that the raw events were too detailed to work with directly, so I had converted them into higher-level activities such as clicks, text entry, application switches, copy/paste, scrolling and shortcuts. I also checked this manually on Dataset A. In one representative session, around 2,348 raw events were reduced to 388 activities, and the reconstructed keyboard input matched the expected text in 96 out of 96 cases. After that validation, I decided to freeze activities.py and treat it as a fixed input for the rest of the experiments. This helped me separate problems in activity extraction from problems in segmentation or process discovery.
So on Day 3, my main question became:
Now that I have reasonable activities, how do I actually recover meaningful pieces of work from them?

## My first attempt – heuristic grouping

My first idea was still fairly simple.
I thought I could look at two activities, check how related they were, and then keep grouping them into the same execution if the relationship looked strong enough.
I used things such as:

* how close they were in time,
* whether they happened in the same application or window,
* whether they involved the same entity,
* whether there was some continuation or context relationship,
* and whether the activity transitions looked similar.
The basic idea was:
“If the activities look related enough, keep them in the same work unit.”
This seemed reasonable when I was designing it, but once I actually evaluated it against the ground truth, the weaknesses became obvious.
The first heuristic result
One early version produced roughly:
* 3,554 logical executions,
* 3,440 candidate segments,
* 454 activities marked UNASSIGNED,
* 640 singleton groups.
At first, some of the numbers looked encouraging. The temporal overlap evaluation showed around 0.7779 F1, with precision around 0.9868 and recall around 0.6420.
But when I looked at the actual grouping structure, the result was much worse.
The pairwise same-process evaluation gave:
* Precision: 0.3618
* Recall: 0.5987
* F1: 0.4511
There were also around 1,160 ground-truth executions that were split across multiple predicted groups, while around 996 predicted groups contained activities from multiple ground-truth executions.
So I had two different problems happening at the same time:
Some real processes were being broken apart.
Some different processes were being merged together.
That made it clear that the seemingly good temporal score was hiding a more serious problem.

## I tried making the heuristic stricter

My next thought was that maybe the rules were simply too relaxed.
So I made the grouping more conservative to try to reduce the over-grouping.
This time I got approximately:

* Precision: 0.752
* Recall: 0.225
* F1: 0.346
Now I had basically created the opposite problem.
The rules were so strict that they were breaking genuine executions apart.
This was one of the first really useful failures of the day.
I realised that I was trying to solve a complicated process-recovery problem with a few hand-tuned thresholds, and there was no single threshold that could fix everything.
That changed my thinking.
Instead of spending the whole day tuning heuristic rules, I decided to try a learned approach.

## Trying machine learning – first as a pairwise problem

My next idea was to let a model learn whether two activities belonged to the same process execution.
Instead of manually saying:
“Similarity above X means same execution,”
I changed the question to:
“Given the relationship between these two activities, can a model predict whether they belong to the same execution?”
I created a family of experiments around this idea under case\_correlation\_ml.
The features included things like:

* time gap,
* activity type,
* application and window context,
* entity relationships,
* explicit triggered\_by relationships,
* structural similarity,
* and other contextual information.
This felt more promising because the model could learn how different pieces of evidence interact instead of me manually assigning everything.

## The pairwise classifier actually looked good

This was one of the more confusing parts of the day.
The first classifier looked reasonably strong.
On the held-out Dataset A split, I got approximately:

* Candidate recall: 0.9111
* Precision: 0.8331
* Recall: 0.6477
* F1: 0.7288
* ROC-AUC: 0.9151
* PR-AUC: 0.8512
So at this point I thought I might finally be close to a good solution.
But then I made an important mistake in how I interpreted the result.
I was looking at the quality of the pairwise predictions.
The actual task, however, is not to produce a list of “these two activities are related” predictions.
I need to turn those predictions into actual contiguous segments.
So I ran the full reconstruction step.
That is where things fell apart.

## The reconstruction over-merged everything

After turning the pairwise predictions into actual process segments, I got approximately:

* Precision: 0.1203
* Recall: 0.9106
* F1: 0.2125
* Boundary F1 at 5 seconds: 0.1376
So the classifier itself was reasonably good at identifying related pairs, but the process reconstruction was joining too many activities together.
The problem was basically that local relationships could chain together.
For example, if:
A is related to B
and
B is related to C
then my reconstruction could effectively create:
A → B → C
even when A and C should not actually belong to the same process execution.
So I was producing very large merged groups.
This was a major conceptual failure.
I wrote down the main lesson for myself:
A good pairwise “same execution?” model does not automatically produce good process boundaries.
That distinction became one of the most important discoveries of the entire project.

## I tried to make the reconstruction stricter again

I did not immediately throw away the idea.
I changed the reconstruction logic and made it stricter to reduce the over-merging.
It improved precision somewhat:

* Precision: 0.1772
* Recall: 0.8839
* F1: 0.2952
But the actual boundary performance was still almost unusable.
The boundary F1 was approximately:
* ±0.5 s: 0
* ±1 s: 0
* ±2 s: 0
* ±5 s: around 0.0027
At this point I stopped trying to patch the same approach.
The problem was no longer a matter of finding a better threshold.
I was simply predicting the wrong thing.

## The major change – I changed the prediction target

This was probably the biggest turning point of Day 3.
I went back to the actual output requirement and asked myself what I really need the model to predict.
The answer was much simpler:
For two consecutive activities:
Activity A → Activity B
I only need to know:
Is there a boundary between these two activities?
So instead of asking:
“Do A and B belong to the same process execution?”
I changed the problem to:
“Should a new segment start between A and B?”
This turned the ML problem into a boundary-detection problem.
That was much closer to the actual output format because once the model predicts the boundaries, I can directly create contiguous segments from them.
The new implementation became case\_segment\_ml\_v6.py.

## I found another important bug while building the boundary model

While working on the new model, I found a subtle problem in my training-label generation.
A lot of the activities I had extracted were point events.
That means:
start time = end time
For example, a click may happen at one exact timestamp.
Normal interval-overlap logic does not work properly for this kind of event. If I treated a point event as a normal interval, its overlap with a ground-truth segment could become zero even though the event clearly happened inside that segment.
That meant some activities were being assigned to the wrong ground-truth process during training.
In one earlier version, this caused almost all transitions to become effectively negative, which made the training data useless.
I had to stop the model work and fix the ownership logic first.
I changed the rule to:

* for point events, use timestamp containment;
* for activities with duration, use temporal overlap.
I also added a regression test specifically for this case.
The final preflight self-test passed all 10 cases.
This was a useful reminder that even a good model can become meaningless if the training labels are wrong.

## Training the final boundary model

Once that bug was fixed, I trained the new v6 model using a session-level split.
The split was:

* 40 sessions for training
* 10 sessions for validation
* 13 sessions held out for final evaluation
I used Logistic Regression for the transition classifier.
I selected the main segmentation settings using the validation data.
The final selected settings were approximately:
* Threshold: 0.65
* Minimum duration: 12 seconds
* Boundary mode: previous activity end
Then I retrained using the training + validation sessions and evaluated on the 13 held-out sessions.

## The v6 results were the first result I was actually comfortable freezing

The transition classifier itself gave:

* Precision: 0.9788
* Recall: 0.9105
* F1: 0.9434
* ROC-AUC: 0.9307
* PR-AUC: 0.9864
But again, I did not want to stop at classifier metrics.
The actual boundary metrics were more important.
I got:
* ±0.5 s: 0.4503
* ±1 s: 0.4651
* ±2 s: 0.5032
* ±5 s: 0.7495
I also calculated an oracle ceiling by giving the segmentation framework correct activity ownership.
The oracle boundary F1 at ±5 seconds was 0.8741, compared to the actual 0.7495.
That told me that the current system was achieving a meaningful part of what was theoretically possible with the current activity representation.
I decided not to endlessly tune v6.
The activity representation was already reasonably stable, and further improvements were starting to depend on the quality and ambiguity of the available evidence.
So I made an important project decision:
Freeze v6 and use it as the segmentation backbone for the rest of the task.
This was useful because otherwise I could have spent the entire remaining time trying to improve one model by a few points.

## Then I realised that segmentation was only half of Task 1

At this point I finally had something that could divide a continuous recording into work segments.
But there was another requirement.
I still needed to answer:
What kind of work does each segment represent?
The output also needs consistent process/workflow labels.
So I started a second, separate problem:
Process/workflow discovery.
This was another important separation in my thinking.
Segmentation answers:
“Where are the work units?”
Workflow discovery answers:
“Which work units are the same kind of work?”

## First process-discovery attempt

My first process-discovery version relied mainly on structural information.
I used things such as:

* activity-type sequence,
* transition structure,
* contextual patterns,
* TF-IDF-style signatures,
* and dimensionality reduction.
The result on the Dataset A holdout was not good.
There were around 519 predicted segments with activity evidence, and the selected clustering configuration produced:
* 5 clusters,
* purity: 0.1104
* ARI: 0.0006
So the segmentation was now much better, but the workflow labels were not.
This was another useful lesson:
Good segmentation does not automatically mean good process discovery.

## I tried a richer representation

Instead of immediately changing the clustering algorithm, I first tried to improve the representation.
I created process\_discovery\_v2.py.
This version combined:

* activity order,
* relationships,
* entity patterns,
* semantic text,
* contextual information,
* structural transitions.
The reasoning was that activity types alone are often too generic.
For example:
CLICK → COPY → SHORTCUT
could occur in many completely different business tasks.
The richer version improved the result somewhat.
The selected configuration had:
* 33 clusters,
* silhouette: 0.1832
* singleton fraction: 0.303
* stability ARI: 1.0
* GT purity: 0.2470
* GT ARI: 0.0175
So this was clearly better than my first attempt, but it was still not strong enough for me to be satisfied.
At that point I deliberately did not keep adding random features.
I wanted to understand the problem first.

## I built a proper process-discovery diagnosis

This was one of the most useful parts of the day.
Instead of saying:
“Maybe one more feature will fix it,”
I built a diagnosis that compared several different representations on the same Dataset A holdout.
I compared:

* activity order,
* relational context,
* entity structure,
* application diagnostics,
* semantic text,
* structural + semantic combinations,
* previous v2 representations,
* ordered sequence similarity.
I also evaluated them using several different measures.
For clustering quality, I looked at:
* purity,
* ARI,
* silhouette.
For whether the representations actually separated workflows in a useful way, I also looked at:
* leave-one-session-out 1-nearest-neighbour accuracy,
* same-process versus different-process similarity.
And I compared different choices of cluster count, including the true number, the best possible number, and the internally selected number.
This was important because Dataset B has no ground truth.
I needed to understand whether the way I selected clusters without labels was at least behaving sensibly on Dataset A first.

## The diagnosis gave me a clear answer

The results finally showed me which representation was actually useful.
The semantic representation was much stronger than the purely structural ones.
On the Dataset A holdout, semantic information had:

* Oracle-k ARI: 0.1462
* Best-k ARI: 0.2457
* Leave-session-out 1NN accuracy: 0.5222
whereas the activity-order representation had a best-k ARI of only 0.0090.
So the difference was not small.
The semantic representation was clearly giving me more useful information for distinguishing process types.
One result that surprised me was that adding more structural information to the semantic representation actually made things worse in this dataset.
That made me stop thinking that “more features must be better.”
Instead, I decided to keep the representation relatively focused.

## I moved to a semantic-first process-discovery approach

Based on those experiments, I created process\_discovery\_final.py.
The main idea was:
Use the semantic information present in the UI, but remove dynamic values so that the clustering does not simply memorise things like IDs, dates or URLs.
I used information such as:

* window titles,
* target fields,
* available text,
* screen text.
For the actual representation, I used character-level TF-IDF because the data contains Japanese text and mixed UI strings, where normal word-based tokenisation is not always ideal.
I also masked dynamic things such as:
* URLs,
* email addresses,
* dates,
* times,
* long numbers,
* ID-like values.
For clustering, I used agglomerative clustering with cosine distance.
I also selected the clustering threshold using an internal combination of:
silhouette + stability − singleton penalty
and explicitly checked reorder stability.
That last check was important to me because I did not want the workflow labels to change simply because the records were processed in a different order.

## Final process-discovery result on Dataset A

The final semantic-first version produced:

* 519 segments with activity evidence,
* 13 sessions,
* 10,713 semantic dimensions,
* threshold: 0.60
* 22 clusters,
* silhouette: 0.5338
* singleton fraction: 0.0455
* stability ARI: 1.0
* reorder stability ARI: 1.0
* GT purity: 0.3554
* GT ARI: 0.1620
This was not perfect, and I did not want to pretend that it was.
But compared with the earlier approaches, it was a clear improvement:
First structural version:  
Purity 0.1104, ARI 0.0006
v2:  
Purity 0.2470, ARI 0.0175
Final semantic-first:  
Purity 0.3554, ARI 0.1620
Since there was no fixed clustering-accuracy target given in the task, and the overall approach was now supported by the representation diagnosis, I decided that this was sufficient to move forward to Dataset B rather than spending the rest of my time trying to perfect an inherently difficult unsupervised problem.
I then committed the final process-discovery implementation.

## Applying the frozen pipeline to Dataset B

After this point, I made another deliberate decision:
Stop changing the algorithms.
I wanted to see what the frozen pipeline actually produced on the unseen Dataset B rather than continually changing the method until I got a result I liked.
The pipeline became:
Dataset B raw events
→ frozen activities.py
→ activities
→ frozen case\_segment\_ml\_v6.py
→ contiguous segments
→ frozen semantic-first process discovery
→ workflow labels
→ final validation
→ outputs/segments.jsonl
Dataset B produced 9,169 activities across 15 sessions.

## Dataset B segmentation

The frozen v6 segmentation model produced:
400 segments across all 15 sessions.
The boundary-model preflight also passed again.
At first, the labels looked like:
WORK\_0001, WORK\_0002, WORK\_0003, etc.
For a moment I wondered whether those were supposed to be the actual workflow labels.
After checking the implementation, I realised they were only temporary segmentation identifiers.
They were there to identify the segments before the workflow-discovery stage.
So I did not manually change them.

## Dataset B workflow discovery

I then ran the final semantic-first process-discovery method independently on Dataset B.
This was important because I did not want to bring Dataset A process labels into Dataset B.
The workflow types were discovered directly from B.
The result was:

* 400 segments with activity evidence,
* 15 sessions,
* 4,294 semantic dimensions,
* threshold: 0.60
* 20 clusters,
* silhouette: 0.3825
* singleton fraction: 0
* stability ARI: 1.0
* reorder stability: 1.0
So the temporary WORK\_\* labels were replaced with 20 workflow labels such as WORKFLOW\_006, WORKFLOW\_004, etc.
There were:
20 unique workflow labels for 400 segments.
No temporary WORK\_\* labels remained.
At this point I had effectively finished the main Task 1 pipeline.

## I added a final validation layer

I did not want to simply trust the intermediate output.
So I created finalize\_segments.py.
Its job was intentionally simple:

* check the required fields,
* check timestamps,
* reject invalid or unresolved labels,
* verify the number of sessions,
* check that durations are positive,
* check for overlaps,
* and finally write exactly the required four fields.
Before running it on the real output, I also tested the finalizer on synthetic cases.
The preflight passed all three tests.
Then the real finalization produced:
* 15 sessions
* 400 segments
* 20 workflow labels
* 0 overlaps
* 0 unresolved segments
and generated:
outputs/segments.jsonl.

## I independently checked the final output

I did one more check instead of assuming that because the finalizer passed, everything was automatically correct.
I independently parsed the final segments.jsonl.
The checks showed:

* 400/400 JSON records parsed successfully,
* required fields were correct,
* no missing values,
* 15 sessions,
* 20 workflow labels,
* no temporary WORK\_\* labels,
* no invalid timestamps,
* no negative or zero durations,
* no overlaps,
* no duplicate identical segments,
* no out-of-order sessions,
* no conflicting labels on identical intervals.
The duration statistics were approximately:
* minimum: 12.58 seconds
* median: 24.38 seconds
* 95th percentile: 44.49 seconds
* maximum: 98.23 seconds.
There were also 177 adjacent pairs with the same workflow label.
I deliberately did not merge those automatically because two consecutive executions of the same workflow can legitimately have the same workflow label. Same label does not necessarily mean the two executions are one execution.
I also noted an important limitation: the output effectively partitions each observed session span continuously. I need to describe this honestly in the final report rather than implying that every second in those intervals has been independently proven to be business work.

## Git and reproducibility

As the pipeline became stable, I also cleaned up the repository.
I adjusted .gitignore so that large generated data and unnecessary intermediate outputs would not accidentally get committed.
At the same time, I decided that the actual required deliverable:
outputs/segments.jsonl
should be committed because it is itself part of the task submission.
I also tried to follow a simple rule for Git:
I should commit something when the milestone actually works, not just because I created a file.
So the history should show the actual progression from activity extraction, to failed experiments, to the final segmentation model, workflow discovery and Dataset B output.

## The biggest lessons from Day 3

Day 3 had a lot of failures, but those failures actually helped me narrow the problem down.

1. Raw events are too detailed
I needed an activity layer before I could reason about business work.
2. Simple temporal heuristics were not enough
They either merged too much or split too much.
3. A good pairwise classifier does not automatically produce good segments
This was one of the biggest things I learned.
The first ML classifier looked strong on pairwise metrics, but the reconstructed segments were still bad because the local relationships chained together.
4. The prediction target mattered
Changing the question from:
“Do these activities belong to the same execution?”
to:
“Is there a boundary between these two consecutive activities?”
made the problem much closer to the actual deliverable.
5. Training-label construction matters just as much as the model
The point-event bug showed me that even a good model can learn nonsense if the ground-truth ownership is generated incorrectly.
6. Segmentation and workflow discovery are different problems
I had to evaluate them separately.
7. More features are not automatically better
The process-discovery diagnosis showed that semantic information was much more useful than many of the structural combinations I tried.
8. Dataset B must remain independent
The workflow labels in B were discovered from B itself instead of copying A's process labels.
9. At some point I had to freeze the system
Once I had a reasonable segmentation model and a supported process-discovery method, continuing to optimise everything indefinitely would not have been practical.

## End of Day 3

By the end of Day 3, the main technical part of Task 1 was effectively complete.
I had gone from raw events to:
activities → boundaries → segments → workflow discovery → final validated segments.jsonl
The final Dataset B output at this point was:

* 15 sessions
* 9,169 activities
* 400 segments
* 20 discovered workflow labels
* 0 overlaps
* 0 unresolved segments
The more important thing for me was that I now understood why the final pipeline looked the way it did.
It was not just one model that happened to produce a file.
It was the result of several failed approaches and changes in problem formulation.

\---

# Day 4 – Task 2, Task 3, Debugging, Testing and Finalization

By the start of Day 4, the main Task 1 pipeline was already working. I had the final segments.jsonl for Dataset B, with 400 inferred segments across all 15 sessions, and the segmentation and workflow-discovery parts had already been frozen.
So Day 4 was mainly about moving from “I can recover the work” to “I understand the work and can show how it can be automated.”
There were still two major tasks left:
Task 2 — understand and analyse the discovered workflows and select an automation opportunity.
Task 3 — build a working automation prototype for the selected workflow.
There was also a lot of debugging and testing involved in both of these.

## How I used AI during implementation

Before getting into Task 2, one thing became very important in how I was managing my time.
Since I had already spent a large part of the available time understanding the problem and experimenting with different approaches, I did not want to spend many hours manually writing every line of boilerplate code.
So for many of the new scripts, I used ChatGPT mainly to create a first draft of the code based on the design I had already decided.
I did not treat that generated code as finished code.
My workflow was more like:
My design
→ ask ChatGPT for a draft implementation
→ run it myself
→ inspect the output
→ find bugs or incorrect assumptions
→ modify/debug the code
→ run it again
→ repeat.
This helped me use my limited time better, but I still wanted to make sure that I understood what the code was doing.
Because I was the one running the scripts on the actual data and debugging the failures, I was able to catch many problems that would not have been obvious just by reading the generated code.
I also created a lot of synthetic tests, again with help from ChatGPT, before trusting the scripts on the real dataset.
For example, instead of only testing on the real 15 Dataset B sessions, I created small artificial examples where I already knew what the correct output should be.
This helped me catch issues such as:

* activities being assigned to two segments,
* boundary cases,
* invalid inputs,
* duplicate IDs,
* unsupported currencies,
* repeated submissions,
* and incorrect state transitions.
Only after those synthetic cases behaved correctly did I run the code on the actual dataset.
This approach became especially useful during Task 1 and Task 2, where some failures were very difficult to understand just by looking at the error message.
When I got stuck on those cases, I used Claude mainly for diagnostics.
Instead of asking it to solve the whole problem, I asked it to write small diagnostic scripts that would calculate things like:
* counts and distributions,
* where activities were being assigned,
* how many overlaps existed,
* how clusters were distributed,
* which cases were anomalous,
* and what the statistical difference was between successful and failed cases.
Those diagnostics made several bugs much easier to understand.
So during implementation, I was mainly using the tools in three different ways:
ChatGPT → draft code + synthetic test generation + debugging discussion
Claude → difficult diagnostic/statistical analysis
Myself → deciding what the result means, checking the actual dataset, debugging, and deciding whether a change should stay
This was much faster than manually writing every script from scratch, but still kept the important reasoning and verification with me.

## Part 1 – Starting Task 2

Once Task 1 was frozen, I started looking at the final segments.jsonl.
At first, I realised that the file itself was not enough to answer the questions in Task 2.
A segment looked something like:
WORKFLOW\_006
But that was only my cluster label.
It was not the real name of the business process.
So I needed to understand what each workflow cluster actually represented.
I also wanted to connect the workflow to its individual occurrences.
For example, conceptually I wanted something like:
WORKFLOW\_006
→ execution 1  
→ execution 2  
→ execution 3  
→ ...
and then understand what those executions were actually doing.
Because Dataset B has no ground truth, I had to be careful here. I could use evidence from the logs to infer what a workflow probably meant, but I could not honestly claim that a cluster was definitely a specific business process without enough evidence.

## Building the Task 2 analysis layer

I created a separate analysis script that combined:
activities.jsonl + segments.jsonl
and used them to calculate workflow-level and execution-level statistics.
The first version looked at things such as:

* occurrence count,
* number of sessions,
* duration,
* applications used,
* application switching,
* activity counts,
* activity-type patterns,
* entity evidence,
* process-related evidence.
I also created generated occurrence IDs such as:
WORKFLOW\_006\_EXEC\_0001
I was careful to keep the terminology correct.
These were my inferred occurrence IDs, not original execution IDs from the source system.
That distinction was important because there was no source-system execution ID available for Dataset B that I could simply reuse.

## I found a bug in my first Task 2 analysis

The first run produced something that immediately looked wrong.
It reported roughly:

* 9,169 activities,
* 9,554 assigned activities,
* and even a negative number of unassigned activities.
That was obviously impossible.
I could not assign 9,554 unique activities when there were only 9,169 activities in total.
So I went back into the assignment logic instead of assuming that the statistics were somehow special.
I found that activities crossing segmentation boundaries could be counted in both neighbouring segments.
The problem was in my Task 2 analysis join logic, not in the actual Task 1 output.
I changed the assignment rule so that every activity could belong to at most one final segment.
For point activities exactly on a boundary, I made the assignment deterministic.
For activities with duration, I assigned them to the segment with the larger temporal overlap.
After the correction, the result became:
* 9,169 activities,
* 400 final segments,
* 15 sessions,
* 20 workflow clusters,
* 9,169 activities assigned exactly once,
* 0 unassigned activities.
This was a good example of why I was not blindly trusting generated code or its output.
The first script ran successfully, but its result was logically impossible.

## Making Task 2 easier to analyse

After fixing the assignment bug, I expanded the output so that I could look at the problem from different levels.
I generated things such as:

* workflow\_summary.csv
* execution\_map.jsonl
* workflow\_evidence.jsonl
* workflow\_semantic\_cues.jsonl
* task2\_report.json
* task2\_anomalies.json
I wanted three different views.
Workflow level
For each workflow cluster:
* how many times it occurred,
* how many sessions it appeared in,
* actor or machine coverage where available,
* recorded time,
* application footprint,
* application switches,
* activity counts,
* entity evidence,
* process evidence.
Execution level
For each individual occurrence:
* workflow ID,
* inferred execution ID,
* session,
* start/end,
* duration,
* application evidence,
* text/window evidence,
* entities,
* activity pattern.
Evidence level
I wanted to preserve representative evidence so I could later answer a much more useful question:
“Why do I think this workflow represents this kind of business work?”
This became the basis for the business-process interpretation step.

## Turning anonymous workflow clusters into business meaning

At this point I had labels such as:
WORKFLOW\_003, WORKFLOW\_004, WORKFLOW\_006, WORKFLOW\_010, etc.
But those names had no business meaning.
I realised that I didn't need another clustering algorithm.
The clustering had already grouped similar segments.
Now I needed to inspect the repeated semantic evidence inside each cluster.
So I created another script:
infer\_business\_types\_v2.py
The idea was to use repeated evidence inside a workflow cluster to suggest a human-readable business-process type.
I deliberately made this conservative.
I did not want the system to do something like:
“I saw an employee ID once, therefore this must be Employee Registration.”
Instead, I looked for repeated evidence such as:

* recurring Word documents,
* recurring browser pages,
* recurring Excel files,
* repeated UI text,
* repeated application combinations.
The output included a suggested process type and a confidence level.

## I decided not to force names when the evidence was weak

The first business-type inference produced:

* 20 workflow clusters,
* 9 high-confidence,
* 1 medium-confidence,
* 10 low or ambiguous.
At first I thought this might mean the approach was failing.
But after looking at the actual evidence, I realised that this was actually safer.
Some clusters contained a mixture of many applications and contexts, such as HR systems, accounting systems, order/inventory systems, Word, Edge and Notepad, without one clearly repeated business artifact.
It would have been worse to confidently invent a process name just to make the report look cleaner.
So I kept the confidence levels and allowed ambiguous workflows to remain ambiguous.
That became an important rule for Task 2:
When the logs do not provide enough evidence, I should say that the workflow is ambiguous instead of pretending that I know what it is.

## Some workflows were much easier to identify

A few clusters had very strong repeated evidence.
WORKFLOW\_003
This was one of the cleanest examples.
A recurring artifact called:
expense\_calc - Excel
appeared in all 17 occurrences.
The workflow repeatedly involved:

* Microsoft Excel,
* Microsoft Edge,
* the financial/accounting system.
So I interpreted it as:
Expense calculation / settlement support
with high confidence.

### WORKFLOW\_010

This one repeatedly contained:
nyusha\_checklist\_shinsotsu\_batch
in 40 out of 41 occurrences.
That strongly suggested:
New-hire onboarding / employee joining verification
WORKFLOW\_011
The recurring artifact:
budget\_analysis
appeared in all 7 occurrences.
I interpreted it as:
Budget analysis / financial planning support
WORKFLOW\_013
This workflow repeatedly contained documents relating to childcare and nursing-care leave, which supported:
Childcare / nursing-care leave administration
WORKFLOW\_016
This repeatedly contained:
kanrisya\_kengen\_shinsei\_tetsuzuki
which supported:
Administrator access / permission request.
These examples were useful because now the cluster IDs were beginning to have understandable business meaning.

## Creating the Task 2 workflow catalogue

After this, I created a human-readable catalogue of all 20 workflows.
For each workflow I included things such as:

* workflow ID,
* inferred business type,
* confidence,
* occurrence count,
* session count,
* recorded time,
* application footprint,
* application switches,
* entity evidence,
* repeated semantic cues,
* representative evidence,
* automation interpretation.
I also explicitly documented that WORKFLOW\_006 was my own internal cluster ID and not a ground-truth business process name.
Similarly, WORKFLOW\_006\_EXEC\_0001 was an inferred occurrence ID, not an original source-system execution ID.
This made the analysis much easier to understand than simply presenting 20 anonymous cluster numbers.

## Selecting an automation candidate

Once I understood the workflows better, I moved to the main business question:
Which of these processes is actually worth automating?
I did not want to simply choose the most frequent workflow.
I looked at several things:
Workload
How often does it happen?
How much recorded time does it consume?
Repeatability
Does the same pattern keep appearing?
Definition clarity
Can I explain what the process actually does from the evidence?
Technical complexity
How many applications are involved?
How much cross-application movement is required?
How many different decision branches are visible?
Human judgment
Does this work involve decisions or approvals that should remain with a person?
Prototype feasibility
Most importantly, could I actually build a credible prototype within the remaining time?
This last point mattered quite a lot because I had limited time left.

## Comparing the main candidates

WORKFLOW\_006
This was the largest candidate:

* 64 occurrences,
* 10 sessions,
* about 26.2 recorded minutes.
At first, it looked like the obvious choice.
But after looking at the evidence more closely, I found that it actually represented a family of related procedures, including supplier and contract-related operations.
It also involved a fairly large application-switch footprint.
So my conclusion was:
Potentially high impact, but too broad for a reliable prototype within the remaining time.

### WORKFLOW\_014

This had:

* 43 occurrences,
* 8 sessions,
* about 18.7 recorded minutes.
But the evidence was split between different types of activities, including outsourced-work procedures and representation/entertainment-expense administration.
Again, it looked valuable, but it did not have a clean enough boundary for me to build a quick prototype confidently.

### WORKFLOW\_010

This had:

* 41 occurrences,
* 9 sessions,
* about 17.8 recorded minutes.
The onboarding evidence was very strong.
However, it involved HR information, more application movement and potentially sensitive employee information.
It also contained business rules that I could not fully recover from the logs.
So it was a strong candidate, but not the easiest one to prototype safely in the remaining time.

## Final shortlist

After comparing the candidates, my final top three were:

1. WORKFLOW\_003 — Expense calculation / settlement support
2. WORKFLOW\_010 — New-hire onboarding / employee joining verification
3. WORKFLOW\_004 — Monthly fixed-amount business-partner list review
The important part was that this was not simply a ranking by frequency.
I selected WORKFLOW\_003 because it gave me the best combination of:
* clear evidence,
* repeated work,
* structured calculations,
* reasonable scope,
* safe prototype boundary,
* and low implementation uncertainty.

## Task 3 – Building the automation prototype

I then moved to Task 3.
The selected workflow was:
WORKFLOW\_003 — Expense calculation / settlement support.
The strongest evidence was:

* 17 occurrences,
* 7 sessions,
* around 7.7 recorded minutes,
* expense\_calc present in all 17 occurrences,
* Excel present in all 17,
* accounting-system interaction in 12.
The visible workflow looked roughly like:
source/accounting information
→ Excel calculation
→ result preparation
→ accounting-system interaction.
One important limitation was that the logs did not reveal the company's actual production accounting formula.
So I made a conscious decision:
I would not pretend that I had recovered the real accounting rules.
Instead, I would build a prototype that demonstrates the automation architecture around the calculation process.
The prototype flow became:
standardized expense data
→ validation
→ calculation
→ exception checking
→ review output
→ human approval
→ mock submission.

## My first prototype was too small

The first version technically worked, but it only demonstrated the calculation on a few rows.
When I looked at it from a reviewer's point of view, I realised that it was not convincing.
A person can easily calculate three or four rows manually.
That does not really demonstrate why automation would be useful.
So I changed the design.
Instead of building a tiny calculator, I decided to make it behave more like an actual employee-facing batch-processing tool.
The new goal became:
Give the system an Excel file, CSV, multiple files, or a directory of files, and let it process the batch automatically.

## Expanding the prototype to realistic batch processing

The updated prototype accepted:

* one CSV,
* one Excel workbook,
* multiple Excel files,
* multiple CSV files,
* a whole directory,
* and multiple worksheets inside a workbook.
For multi-sheet Excel files, the sheets were combined into one processing batch.
This made the prototype much closer to a realistic enterprise automation workflow rather than a simple demonstration script.

## I also increased the test-data size

I generated much larger demo inputs so that the prototype was not only tested on tiny examples.
The main test files included:

* a 10,000-row Excel file,
* a 10,000-row multi-sheet Excel file,
* a 10,000-row anomaly-heavy Excel file,
* and a 5,000-row CSV.
This gave me a much better idea of whether the batch-processing logic was actually working at a reasonable scale.

## Expanding the expense data model

The prototype also moved beyond a few simple fields.
The input data included things such as:

* expense ID,
* employee reference,
* department,
* expense date,
* category,
* merchant,
* project code,
* payment method,
* reimbursable flag,
* receipt availability,
* quantity,
* unit amount,
* currency,
* FX rate,
* tax rate,
* discount rate,
* source reference.
The output then calculated things such as:
* subtotal,
* discount,
* taxable amount,
* tax,
* total amount,
* reporting amount.
I also added analytics such as:
* unique employees,
* unique departments,
* unique projects,
* unique merchants,
* reimbursable spend,
* non-reimbursable spend,
* average/median/minimum/maximum transaction,
* receipt coverage,
* duplicate IDs,
* possible duplicates,
* missing receipts,
* high-value exceptions.
I also added breakdowns by employee, department, category, project, merchant, payment method, currency and month.

## Keeping the accounting rules configurable

This was an important design decision.
Because the logs did not tell me the company's real accounting formula, I used transparent demonstration rules such as:
subtotal = quantity × unit amount
discount = subtotal × discount rate
taxable = subtotal − discount
tax = taxable × tax rate
total = taxable + tax
reporting total = total × FX rate
But I kept these rules configurable.
I did not present them as the company's actual accounting policy.
The point of the prototype was to demonstrate the automation architecture.
In a real deployment, the approved business rules would be provided by the process owner and would replace my demonstration configuration.

## Adding enterprise-style controls

I also wanted the prototype to feel like an actual workflow rather than a calculator.
So I added explicit processing states:
INPUT
→ VALIDATED
→ CALCULATED
→ READY\_FOR\_APPROVAL
→ APPROVED
→ SUBMITTED
Invalid input goes to:
BLOCKED
I also added:

* validation,
* exception reports,
* audit logs,
* deterministic batch IDs,
* a human approval gate,
* idempotent submission,
* and a mock submission layer.
The prototype does not contact a real accounting system.
That was intentional because I did not have access to the real system or enough information to implement that safely.

## Stress-testing the automation

I then ran the prototype against the larger generated datasets.
The results were:
10,000-row clean Excel
→ READY\_FOR\_APPROVAL
5,000-row CSV
→ READY\_FOR\_APPROVAL
10,000-row multi-sheet Excel
→ READY\_FOR\_APPROVAL
10,000-row anomaly-heavy Excel
→ BLOCKED
The important thing here was that the bad input was not simply processed anyway.
The system detected the deliberate anomalies and stopped the batch.
That gave me some confidence that the prototype was not only designed for perfect input but also had a basic safe-failure path.

## Adding unit and integration tests

I then added tests for different parts of the workflow.
The tests covered:
Normal calculation + multi-sheet Excel
Checking:

* Excel input,
* multiple sheets,
* calculation correctness,
* output workbook,
* analytics.
Directory batch processing
Checking:
* multiple files,
* fan-out processing,
* manifest creation.
Invalid data
Checking cases such as:
* duplicate expense IDs,
* unsupported currencies.
These should result in:
BLOCKED
Warning path
I also checked that a recoverable warning, such as a missing receipt, does not automatically become a hard failure.
Idempotent submission
I tested:
submit
→ submit again
and checked that the same transaction ID was returned.
The final test run was:
5 tests — all passed.
This was another place where the synthetic tests were useful.
Before trusting the real data, I could create small artificial cases where I knew exactly what should happen.

## One command-line mistake during testing

During the end-to-end testing, I made one simple mistake.
After the 10,000-row run, I tried to approve the batch using the parent directory rather than the actual batch directory.
The command pointed to something like:
enterprise\_expenses\_10000
instead of:
enterprise\_expenses\_10000/BATCH-...
That caused an OSError because the expected state.json was not in the parent directory.
I checked the directory structure, found the mistake and reran the command using the actual batch directory.
The process then worked correctly.
This was not a bug in the automation itself — it was simply me pointing the command at the wrong path.
I still kept the incident in my notes because it was part of the actual debugging process.

## Completing the full approval and submission lifecycle

After correcting the path, the prototype successfully followed:
READY\_FOR\_APPROVAL
→ APPROVED
→ SUBMITTED
The approval recorded:

* the approver,
* and the reason for approval.
The mock submission then generated a transaction ID.
I submitted the same batch again to check idempotency.
The system remained in the SUBMITTED state and returned the same transaction identity instead of creating a duplicate.
That confirmed that the approval/submission lifecycle I had designed was actually working end-to-end.

## Making sure the prototype looked like an automation workflow, not just a calculator

At the end, I checked whether the prototype really demonstrated an enterprise-style automation flow.
The final prototype included:
batch processing

large data volume

multi-file input

multi-sheet Excel

validation

exception handling

deterministic calculations

analytics

human approval

audit trail

state management

idempotency

safe mock submission.
At the same time, I explicitly documented what was not production-ready:

* no real accounting API,
* no production authentication/authorization,
* no confirmed production accounting rules,
* no real reconciliation,
* no rollback implementation,
* no production monitoring/deployment infrastructure.
I thought it was important to separate what I had actually demonstrated from what would require access to the real enterprise environment.

## Final report updates

After completing Task 2 and Task 3, I updated the report so that it covered not only the workflow analysis but also the prototype.
I made sure the report explained:

* why I selected WORKFLOW\_003,
* why I chose that particular prototype scope,
* why I used a deterministic Python implementation,
* what manual work remains,
* what kind of impact I expect,
* what risks remain,
* and why the prototype was feasible within the available time.
I also avoided claiming unrealistic production savings from the short recorded durations.
Instead, I described the benefit mainly in terms of reducing repetitive calculation, data preparation and verification work.

## Final project cleanup and documentation

After the actual technical work was completed, I moved to the final documentation stage.
At this point, all the project files were essentially finished, so the remaining task was document refinement.
I took my:

* final work log,
* final report,
* and the completed project context,
and used Gemini as a final documentation reviewer.
I gave it the documents and asked it to help structure them properly, improve the flow, make the sections easier to follow and make sure that the important decisions and work progression were represented clearly.
I did not use it to invent technical content.
The implementation and actual results were already finished.
The purpose of this last AI step was mainly to improve how the work was presented and organized.
I reviewed the suggested changes myself and then incorporated the parts that made the documents clearer.

## Final Git work

Once the code, outputs, reports and work log were all in their final form, I added the finalized documentation to the repository.
I then made the final Git commit after checking that the important project files were present and that the repository contained the required deliverables.
Finally, I uploaded the completed project to my private GitHub repository.
At that point, the project had gone through the full cycle:
problem understanding
→ solution design
→ implementation
→ failed approaches
→ debugging
→ validation
→ workflow discovery
→ automation candidate selection
→ prototype
→ testing
→ report/work-log refinement
→ final repository submission.

## End of Day 4

By the end of Day 4, I had completed the remaining technical and documentation work.
Task 1 had produced the final segmented workflow output.
Task 2 had turned those anonymous workflow clusters into a structured analysis with business-process interpretations, workload analysis and automation candidates.
Task 3 had turned one of those candidates into a working prototype with batch processing, validation, exception handling, approval, audit logging, mock submission and idempotency.
The final prototype was not presented as a production system because several production-specific details were simply not available from the dataset. Instead, I tried to make the prototype demonstrate the part that I could actually justify from the evidence.
The last step was documentation refinement and repository cleanup.
I reviewed the final files, refined the work log and report with the help of Gemini, added the completed files to the repository, made the final commit and uploaded the project to my private GitHub repository.
At this point, all the planned project work and documentation were completed.




Extended Day – Building a Second Enterprise Automation Prototype

After finishing the main project, I still had around some extra hours available because of the extension of  deadline by one day. At first I considered building another small automation around WORKFLOW_004, which was the monthly fixed-amount business-partner list review workflow. The more I thought about it, the less convinced I was that it was a good use of those remaining hours. The core operation would mostly be comparing one list with another and generating a report, which could be done with a normal Python script. Adding MCP on top of that would not create much extra value.

So I went back to the Task 2 analysis and looked again at the larger WORKFLOW_006 family. This workflow appeared 64 times across 10 sessions and covered around 26.2 minutes of recorded activity. More importantly, the evidence showed repeated supplier and contract procedures, including supplier registration, contract-related work and contract cancellation or termination. The workflow also involved several applications and a lot of application switching. That made it a much better fit for an AI-assisted tool system than simply comparing two spreadsheets.

I therefore changed the plan for the extra prototype. Instead of making another ordinary automation, I decided to build a Supplier and Contract Operations Copilot using MCP.

The main question I wanted to answer was not just, "Can AI run a Python script?" I wanted the AI to actually have access to several useful business capabilities and decide which ones were needed for a request. That is where MCP started making more sense to me.

The idea became something like:

User request
    ↓
AI assistant
    ↓
MCP
    ↓
Supplier / contract / document / workflow tools
    ↓
Deterministic validation and policy checks
    ↓
Prepared action
    ↓
Human approval
    ↓
Controlled submission

I made an important architectural decision here. The LLM would not be responsible for making up business rules or directly deciding whether something was safe to submit. The Python service would still handle validation, policy checks, state changes and audit logging. MCP would provide the interface through which an AI host could discover and use those business capabilities.

Designing it like a real enterprise system

I did not want the prototype to depend on one company's exact software because the logs did not provide the real production APIs or system configuration.

Instead, I separated the business logic from the external systems using interfaces for things such as:

supplier/business-partner master;
contract management;
document storage;
workflow and approval;
e-signature;
audit storage.

For the prototype, I used mock adapters backed by a local database. The idea was that a real company could later replace the adapters with integrations to its own systems without rewriting the MCP tools or the main business logic.

I also mapped the interfaces to realistic enterprise products that could serve the same roles in a real deployment, such as SAP S/4HANA for supplier master data, SAP Ariba Contracts for contract management, ServiceNow for workflow and approval, SharePoint for controlled documents and DocuSign for signing.

I kept these as reference integrations rather than pretending that the prototype was actually connected to those systems.

Defining the actual capabilities

Instead of exposing one large function, I created a group of smaller business tools.

The MCP server exposes capabilities such as:

search_business_partners
get_business_partner
list_partner_contracts
get_contract
check_request_completeness
find_duplicate_candidates
assess_contract_request
prepare_contract_case
request_human_approval
approve_case
submit_case
get_case

The supported request types were:

supplier_registration
contract_creation
contract_amendment
contract_termination

This made the product feel much more like an operations assistant instead of a wrapper around one script.

For example, a request such as:

"Check whether this supplier already exists, see whether they have an active contract, and prepare the registration request."

can involve several different tools before the final result is produced.

The AI can search the supplier master, inspect related contracts, check for possible duplicates, validate the required information and prepare a request for review.

Adding real safety boundaries

Because this is a business-process automation involving suppliers and contracts, I did not want the prototype to behave like an unrestricted AI agent.

I added explicit policy checks for situations such as:

duplicate supplier candidates;
missing required information;
unsupported currencies;
high-value contract changes;
contract termination when open obligations exist;
invalid state transitions;
attempts to submit without approval.

For example, if a contract has unresolved obligations, a termination request is blocked rather than simply being passed through.

The state machine became:

DRAFT
  ↓
PENDING_APPROVAL
  ↓
APPROVED
  ↓
SUBMITTED

with:

BLOCKED

for hard failures.

The service does not allow a blocked case to be approved, and it does not allow a case to be submitted before approval.

I also added deterministic case IDs, audit events and idempotent submission handling so that retrying an already completed operation does not create another submission identity.

Building the mock enterprise environment

To make the prototype more realistic, I generated a non-trivial internal dataset rather than working with only a few hard-coded examples.

The test environment contains more than 1,000 partner records and more than 1,200 contract records, along with relationships between partners, contracts and supporting information.

This allowed me to test searches, contract lookups, duplicate detection, termination checks and state transitions against something closer to a real service workload.

The important point was that the external systems were mocked, but the interfaces and business flow were designed as if those systems were real.

Writing a much larger test suite

I also wanted to avoid repeating the mistake of building a prototype and testing it with only one or two examples.

So I made claude write a large software-style test suite covering:

policy rules;
required-field validation;
supported currencies;
state-machine transitions;
approval requirements;
submission restrictions;
duplicate detection;
contract lookup behavior;
high-value change thresholds;
open-obligation termination blocking;
deterministic case IDs;
audit logging;
lookup limits;
invalid and malicious queries;
REST connector configuration;
MCP tool registration;
tool signatures and documentation;
thread-safety of tool calls;
and other edge cases.

I deliberately generated many cases around the same rules instead of relying on a handful of examples. The final full test run completed with:

457 tests
457 passed
0 failed

in about 4.2 seconds.

That gave me much more confidence in the internal business logic than a small demo test would have.

Testing the security side as well

Because the server accepts user-provided search input, I also added malicious-input cases resembling SQL injection, path traversal, script injection and other malformed queries.

The purpose was not to claim that the prototype had solved every possible production security problem. It was to make sure that the basic service layer did not break when it received obviously unsafe or unexpected input.

I also added configuration validation for external REST connectors so that only expected HTTP/HTTPS endpoints could be used.

Building the MCP layer

The next step was connecting the deterministic service to MCP.

The MCP server exposes the business capabilities as tools instead of exposing the internal implementation directly.

I also added a policy resource so the active configured rules can be inspected separately from the tool calls.

For local development, the server is designed to run through the official MCP development flow and can be inspected through an MCP-compatible environment.

I also created a separate runtime verification script intended to test the actual MCP protocol using an in-memory client rather than depending on a real network deployment. The main test suite also contains local MCP wiring tests so that the server's tool registration and function contracts can be checked independently.

Building an actual end-to-end demo

I wanted the final demonstration to show something more meaningful than just:

tool called
→ response returned

The demo was designed around realistic operations.

For example, a supplier-registration request can follow:

search supplier
      ↓
check duplicate candidates
      ↓
inspect existing contracts
      ↓
validate required information
      ↓
assess request
      ↓
prepare case
      ↓
request approval
      ↓
approve
      ↓
submit

I also included a contract-termination example where the system detects open obligations and blocks the action.

This was particularly useful because it demonstrated the difference between an AI that can call tools and an AI that is operating inside a controlled business process.

Final smoke test

I ran a small end-to-end demonstration after the larger unit suite.

The smoke test successfully showed:

supplier search returning real mock records;
a termination request being blocked when open obligations existed;
a valid supplier-registration case being created;
the case moving through the approval process;
and the final mock submission producing a deterministic submission ID.

This gave me a simple way to demonstrate the whole system without needing to connect it to a real enterprise environment.

Keeping the prototype honest

One of the most important decisions during this extended work was not to claim more than the dataset supports.

The logs gave me evidence that supplier/business-partner and contract-related work existed, and that several related procedures occurred repeatedly. They did not tell me the company's exact APIs, approval policy, required master-data fields or complete production business rules.

So I treated the prototype as:

evidence-backed workflow
+
reasonable enterprise assumptions
+
replaceable mock integrations

rather than pretending that I had reproduced the company's actual internal system.

That also meant the "submit" operation remained mocked.

No real supplier or contract record was changed.

Final result of the extended work

By the end of the additional work, I had built a second automation prototype that was quite different from the original expense automation.

The first automation was:

WORKFLOW_003
Expense calculation
        ↓
deterministic batch-processing system

The second became:

WORKFLOW_006
Supplier / contract administration
        ↓
MCP-based operations copilot
        ↓
multiple enterprise-style tools
        ↓
deterministic policy engine
        ↓
human approval
        ↓
controlled mock submission

The main thing I learned from this extension was that MCP only becomes interesting when the AI has several meaningful capabilities to use. Simply putting MCP in front of a Python function would not have added much value. By moving to a multi-system supplier and contract workflow, MCP became a useful way to expose several business capabilities while keeping the important rules and safety checks inside the deterministic service


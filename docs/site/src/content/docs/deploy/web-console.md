---
title: Web Console
description: A browser chat page for the Platform Agent on installs with no chat platform, reached through kubectl port-forward.
sidebar:
  order: 9
---

The web console is a chat page for the Platform Agent that runs inside the cluster. It is for installs where Slack or Google Chat is not set up yet — an evaluation cluster, a workshop seat, a demo — so you can talk to the agent from a browser. It is off by default.

## What it does

Each browser tab opens its own agent session. Messages you type go to the Platform Agent as turns in that session, the same way a chat platform delivers them, and the agent's reply comes back to the page. A turn that calls tools can take several minutes; the console waits up to five minutes for a reply. When the agent proposes a change, it opens a pull request, as it does from any other chat surface.

The side panel lists the agent's recent sessions by title, including the triage sessions the event watcher opens. Each entry shows the session's title, its source, its message count and when it was last active, but no message content. You cannot open or post into a session the console did not create.

## How it is reached

The console is reachable through `kubectl port-forward` and no other way. The chart renders its Service as `ClusterIP`, and a NetworkPolicy refuses every connection to the console pod from the pod network. A port-forward enters from the node, which NetworkPolicy does not govern. In practice, whoever holds `pods/portforward` on the install namespace can use the console.

The console holds the agent's API key, from the same Secret the agent reads, and attaches it to the requests it sends the agent. The key does not reach the browser. There is no login page and no per-user identity: every turn reaches the agent as the console.

Do not expose the console through a LoadBalancer, an Ingress or a NodePort. Anyone who could reach it would be able to drive the Platform Agent. The chart does not offer a way to change the Service type, and the console refuses any request whose `Host` is not `localhost`, `127.0.0.1` or `::1`.

## Turning it on

Set `webConsole.enabled: true`, or install with the `values-poc.yaml` overlay that ships in the chart:

```bash
helm install kube-agents charts/kube-agents \
  --namespace kube-agents --create-namespace \
  -f charts/kube-agents/values-poc.yaml \
  --set platformAgent.harness.projectId=YOUR_PROJECT \
  --set platformAgent.harness.clusterName=YOUR_CLUSTER \
  --set platformAgent.harness.location=YOUR_LOCATION
```

The console's Deployment and Service are named `<release>-web-console`, so `kube-agents-web-console` for the release above. Once the Deployment is ready, forward its port and open the page:

```bash
kubectl port-forward -n kube-agents svc/kube-agents-web-console 8080:8080
```

Then open `http://localhost:8080`. The `8080:8080` assumes the default `webConsole.service.port`.

## What to expect when something is wrong

The badge in the header shows whether the console can reach the agent. It reads "Agent unreachable" while the agent pod is starting. It reads "No agent API key" when the console started without one, and in that state every turn fails. A failed turn shows its error in the chat, including the agent's own message when the agent returned one. The console does not fall back to answering from the model directly, so a reply in the page always came from the Platform Agent.

If you send a second message before the first has been answered, the console refuses it. Wait for the reply, then send again.

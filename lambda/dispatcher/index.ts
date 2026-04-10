/**
 * Claw Boutique – Lambda Dispatcher
 * ----------------------------------
 * Consumes SNS messages and routes inbound events to Bedrock Agent (WhatsApp)
 * or the OpenClaw gateway (SES email, WhatsApp statuses).
 *
 * Supported event types
 * ─────────────────────
 * AWS End User Messaging Social (WhatsApp) events
 *    Delivered by the service as SNS notifications.  The SNS `Message` field
 *    contains a JSON string whose top-level key is `whatsAppWebhookEntry`.
 *    That value is ITSELF another JSON-encoded string (a second serialisation
 *    layer performed by End User Messaging Social before publishing to SNS).
 *    We must therefore JSON.parse() twice:
 *
 *      SNS record
 *        └─ record.Sns.Message          ← first JSON.parse()  → outer envelope
 *             └─ .whatsAppWebhookEntry  ← second JSON.parse() → WhatsApp payload
 *                  ├─ .entry[].changes[].value.messages[]     (inbound messages)
 *                  └─ .entry[].changes[].value.statuses[]     (delivery receipts)
 *
 *    Routing:
 *      - All messages → routed to Bedrock Agent (Nova Lite) for customer support,
 *        with reply sent back via EUMS.
 *    Seller commands come through the Telegram bot (handled by OpenClaw directly).
 *
 * Environment variables
 * ─────────────────────
 *   OPENCLAW_GATEWAY_URL      – Base URL of the OpenClaw gateway (EKS NLB)
 *   OPENCLAW_GATEWAY_TOKEN    – Bearer token sent in every request to OpenClaw
 *   BEDROCK_AGENT_ID          – Bedrock Agent ID
 *   BEDROCK_AGENT_ALIAS_ID    – Bedrock Agent Alias ID
 *   WHATSAPP_PHONE_NUMBER_ID  – EUMS origination phone number ID
 *   (Seller commands arrive via Telegram, not through this Lambda)
 */

import axios, { AxiosError } from "axios";
import {
  BedrockAgentRuntimeClient,
  InvokeAgentCommand,
} from "@aws-sdk/client-bedrock-agent-runtime";
import {
  SocialMessagingClient,
  SendWhatsAppMessageCommand,
} from "@aws-sdk/client-socialmessaging";
import type {
  SNSEvent,
  SNSEventRecord,
  Context,
  Callback,
} from "aws-lambda";

// ---------------------------------------------------------------------------
// Environment
// ---------------------------------------------------------------------------

const GATEWAY_URL = (process.env.OPENCLAW_GATEWAY_URL ?? "").replace(/\/$/, "");
const GATEWAY_TOKEN = process.env.OPENCLAW_GATEWAY_TOKEN ?? "";
const BEDROCK_AGENT_ID = process.env.BEDROCK_AGENT_ID ?? "";
const BEDROCK_AGENT_ALIAS_ID = process.env.BEDROCK_AGENT_ALIAS_ID ?? "";
const WHATSAPP_PHONE_NUMBER_ID = process.env.WHATSAPP_PHONE_NUMBER_ID ?? "";
const STORE_API_URL = (process.env.STORE_API_URL ?? "").replace(/\/$/, "");

if (!GATEWAY_URL) {
  console.warn("[dispatcher] OPENCLAW_GATEWAY_URL is not set – SES/status POSTs will fail");
}
if (!BEDROCK_AGENT_ID || !BEDROCK_AGENT_ALIAS_ID) {
  console.warn("[dispatcher] BEDROCK_AGENT_ID or BEDROCK_AGENT_ALIAS_ID is not set – WhatsApp messages will fail");
}
if (!WHATSAPP_PHONE_NUMBER_ID) {
  console.warn("[dispatcher] WHATSAPP_PHONE_NUMBER_ID is not set – WhatsApp replies will fail");
}

// ---------------------------------------------------------------------------
// AWS SDK clients
// ---------------------------------------------------------------------------

const bedrockAgentClient = new BedrockAgentRuntimeClient({});
const socialMessagingClient = new SocialMessagingClient({});

// ---------------------------------------------------------------------------
// Structured logger
// ---------------------------------------------------------------------------

type LogLevel = "INFO" | "WARN" | "ERROR";

function log(level: LogLevel, message: string, extra?: Record<string, unknown>): void {
  console[level === "ERROR" ? "error" : level === "WARN" ? "warn" : "log"](
    JSON.stringify({
      timestamp: new Date().toISOString(),
      level,
      message,
      ...extra,
    })
  );
}

// ---------------------------------------------------------------------------
// HTTP helper
// ---------------------------------------------------------------------------

async function postToGateway(path: string, body: unknown): Promise<unknown> {
  return postToUrl(`${GATEWAY_URL}${path}`, body);
}

async function postToUrl(url: string, body: unknown): Promise<unknown> {
  try {
    const response = await axios.post(url, body, {
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${GATEWAY_TOKEN}`,
      },
      timeout: 25_000, // 25 s – allow time for agent processing
    });

    log("INFO", `POST succeeded`, {
      status: response.status,
      url,
    });
    return response.data;
  } catch (err) {
    const axiosErr = err as AxiosError;
    log("ERROR", `POST failed`, {
      url,
      status: axiosErr.response?.status,
      responseBody: axiosErr.response?.data,
      errorMessage: axiosErr.message,
    });
    throw err;
  }
}

/**
 * Invoke the Bedrock Agent with the customer's message text and return the
 * agent's reply by collecting all streaming response chunks.
 */
async function invokeBedrockAgent(senderPhone: string, messageText: string): Promise<string> {
  const command = new InvokeAgentCommand({
    agentId: BEDROCK_AGENT_ID,
    agentAliasId: BEDROCK_AGENT_ALIAS_ID,
    sessionId: senderPhone.replace(/\+/g, ""),
    inputText: messageText,
  });

  const response = await bedrockAgentClient.send(command);
  let replyText = "";
  if (response.completion) {
    for await (const event of response.completion) {
      if (event.chunk?.bytes) {
        replyText += new TextDecoder().decode(event.chunk.bytes);
      }
    }
  }
  return replyText;
}

/**
 * Submit a WhatsApp survey rating reply to the Store API review endpoint.
 * Returns the review response or null if the API call fails.
 */
async function submitWhatsAppReview(phone: string, rating: number): Promise<{ action: string; customer_name?: string } | null> {
  if (!STORE_API_URL) {
    log("WARN", "STORE_API_URL not set, cannot submit WhatsApp review");
    return null;
  }
  try {
    const resp = await axios.post(`${STORE_API_URL}/api/reviews/from-whatsapp`, {
      phone,
      rating,
    }, { timeout: 10_000 });
    return resp.data as { action: string; customer_name?: string };
  } catch (err) {
    const axiosErr = err as AxiosError;
    log("WARN", "WhatsApp review submission failed", {
      phone,
      rating,
      status: axiosErr.response?.status,
      error: axiosErr.message,
    });
    return null;
  }
}

/**
 * Send a WhatsApp text reply via AWS End User Messaging Social (EUMS).
 */
async function sendWhatsAppReply(to: string, text: string): Promise<void> {
  const sendCmd = new SendWhatsAppMessageCommand({
    originationPhoneNumberId: WHATSAPP_PHONE_NUMBER_ID,
    metaApiVersion: "v21.0",
    message: Buffer.from(
      JSON.stringify({
        messaging_product: "whatsapp",
        to,
        type: "text",
        text: { body: text },
      })
    ),
  });
  await socialMessagingClient.send(sendCmd);
}

// ---------------------------------------------------------------------------
// WhatsApp payload types (End User Messaging Social)
// ---------------------------------------------------------------------------

/**
 * An individual inbound WhatsApp message (text, image, audio, document, …).
 * Only the fields we care about for routing are typed here.
 */
interface WhatsAppMessage {
  id: string;
  from: string;
  timestamp: string;
  type: string;
  text?: { body: string };
  interactive?: { button_reply?: { title: string }; list_reply?: { title: string } };
  image?: { id: string; mime_type: string; sha256: string; caption?: string };
  audio?: { id: string; mime_type: string; sha256: string };
  document?: { id: string; mime_type: string; sha256: string; filename?: string };
  [key: string]: unknown; // allow any media type pass-through
}

/** Delivery / read receipt for a previously sent outbound message. */
interface WhatsAppStatus {
  id: string;
  recipient_id: string;
  status: "sent" | "delivered" | "read" | "failed";
  timestamp: string;
  errors?: Array<{ code: number; title: string }>;
  [key: string]: unknown;
}

interface WhatsAppChangeValue {
  messaging_product: string;
  metadata: { display_phone_number: string; phone_number_id: string };
  contacts?: Array<{ profile: { name: string }; wa_id: string }>;
  messages?: WhatsAppMessage[];
  statuses?: WhatsAppStatus[];
}

interface WhatsAppChange {
  value: WhatsAppChangeValue;
  field: string;
}

interface WhatsAppEntry {
  id: string;
  changes: WhatsAppChange[];
}

/** The fully decoded inner WhatsApp webhook payload (after the double-parse). */
interface WhatsAppWebhookPayload {
  object: string;
  entry: WhatsAppEntry[];
}

/** The outer SNS envelope published by End User Messaging Social. */
interface EUMSOuterEnvelope {
  /**
   * whatsAppWebhookEntry is a JSON-encoded STRING – not an object.
   * End User Messaging Social serialises the WhatsApp payload to JSON and
   * stores that string inside the outer JSON object.  You must call
   * JSON.parse() on this value to obtain the WhatsAppWebhookPayload.
   */
  whatsAppWebhookEntry: string;
}

// ---------------------------------------------------------------------------
// Record processors
// ---------------------------------------------------------------------------

/**
 * Handles an End User Messaging Social (WhatsApp) SNS record.
 *
 * Double-parse explanation
 * ────────────────────────
 * AWS End User Messaging Social publishes events to SNS as follows:
 *
 *   SNS.Message = JSON.stringify({
 *     whatsAppWebhookEntry: JSON.stringify(actualWhatsAppPayload)
 *   })
 *
 * So when we receive the SNS notification:
 *   Step 1 – the Lambda runtime (or the SNS SDK) already parses the outer
 *             SNS wrapper, giving us `record.Sns.Message` as a raw string.
 *   Step 2 – we JSON.parse(record.Sns.Message) to get the outer envelope
 *             object, which has a `whatsAppWebhookEntry` string field.
 *   Step 3 – we JSON.parse(outerEnvelope.whatsAppWebhookEntry) to get the
 *             actual WhatsApp webhook payload (entries, changes, messages /
 *             statuses).
 *
 * If we only do one parse we are left holding a string, not the payload we
 * need – this is the most common pitfall when wiring up this integration.
 */
async function handleWhatsAppRecord(record: SNSEventRecord): Promise<void> {
  const snsMessageRaw = record.Sns.Message;

  // ── Step 2: parse the outer EUMS envelope ────────────────────────────────
  let outerEnvelope: EUMSOuterEnvelope;
  try {
    outerEnvelope = JSON.parse(snsMessageRaw) as EUMSOuterEnvelope;
  } catch (err) {
    log("ERROR", "Failed to parse EUMS outer SNS envelope", {
      messageId: record.Sns.MessageId,
      raw: snsMessageRaw.slice(0, 500),
    });
    return; // non-retryable parse error – skip this record
  }

  if (!outerEnvelope.whatsAppWebhookEntry) {
    log("WARN", "EUMS envelope missing whatsAppWebhookEntry – skipping", {
      messageId: record.Sns.MessageId,
      keys: Object.keys(outerEnvelope),
    });
    return;
  }

  // ── Step 3: parse the inner WhatsApp payload (the double-parse) ──────────
  let innerParsed: Record<string, unknown>;
  try {
    innerParsed = JSON.parse(outerEnvelope.whatsAppWebhookEntry) as Record<string, unknown>;
  } catch (err) {
    log("ERROR", "Failed to parse inner whatsAppWebhookEntry JSON", {
      messageId: record.Sns.MessageId,
      raw: outerEnvelope.whatsAppWebhookEntry.slice(0, 500),
    });
    return;
  }

  // EUMS sends the inner payload in two possible formats:
  //   Format A (Meta Graph API style): {"object":"whatsapp_business_account","entry":[...]}
  //   Format B (EUMS style):           {"id":"...","changes":[...]}  — the entry itself
  // We normalise to Format A.
  let entries: WhatsAppEntry[];
  if (Array.isArray(innerParsed.entry)) {
    entries = (innerParsed as unknown as WhatsAppWebhookPayload).entry;
  } else if (Array.isArray(innerParsed.changes)) {
    // Format B: the inner payload IS a single entry
    entries = [innerParsed as unknown as WhatsAppEntry];
  } else {
    log("WARN", "Inner payload has neither entry[] nor changes[] – skipping", {
      messageId: record.Sns.MessageId,
      keys: Object.keys(innerParsed),
    });
    return;
  }

  log("INFO", "Processing WhatsApp webhook payload", {
    messageId: record.Sns.MessageId,
    entryCount: entries.length,
  });

  // Iterate over all entries and their changes
  for (const entry of entries) {
    for (const change of entry.changes ?? []) {
      const value = change.value;

      // ── Inbound messages (text, media, etc.) ────────────────────────────
      if (value.messages && value.messages.length > 0) {
        log("INFO", "Routing inbound WhatsApp messages", {
          count: value.messages.length,
          phoneNumberId: value.metadata?.phone_number_id,
        });

        // Route each message through Bedrock Agent and reply directly to customer
        for (const msg of value.messages) {
          // WhatsApp 'from' field omits the '+' prefix; normalise to E.164
          const rawFrom = msg.from ?? "";
          const senderPhone = rawFrom.startsWith("+") ? rawFrom : `+${rawFrom}`;
          const messageText =
            msg.text?.body ??
            msg.interactive?.button_reply?.title ??
            msg.interactive?.list_reply?.title ??
            "";

          if (!messageText) {
            log("WARN", "Skipping non-text message", {
              type: msg.type,
              from: senderPhone,
            });
            continue;
          }

          // Seller commands go through WhatsApp self-chat → OpenClaw (linked device).
          // All messages to the WABA number (including from the seller) are routed
          // to the Bedrock Agent as normal customer interactions.

          // Check if this is a survey rating reply (single digit 1-5)
          const trimmed = messageText.trim();
          if (/^[1-5]$/.test(trimmed)) {
            const rating = parseInt(trimmed, 10);
            log("INFO", "Detected survey rating reply", { from: senderPhone, rating });

            const reviewResult = await submitWhatsAppReview(senderPhone, rating);
            if (reviewResult) {
              const name = reviewResult.customer_name || "there";
              let replyMsg: string;
              if (rating >= 4) {
                replyMsg = `Thank you${name !== "there" ? ` ${name}` : ""}! We're glad you had a great experience. See you next time!`;
              } else if (rating === 3) {
                replyMsg = `Thanks for your feedback${name !== "there" ? ` ${name}` : ""}. We'd love to do better next time! Let us know if there's anything specific we can improve.`;
              } else {
                replyMsg = `We're sorry to hear that${name !== "there" ? ` ${name}` : ""}. Our store owner has been notified and will follow up with you personally. We appreciate your feedback.`;
              }
              await sendWhatsAppReply(senderPhone, replyMsg);
              log("INFO", "Survey reply processed and response sent", { from: senderPhone, action: reviewResult.action });
              continue;
            }
            // If review submission failed (e.g. no order found), fall through to Bedrock Agent
            log("INFO", "Review submission failed, falling through to Bedrock Agent", { from: senderPhone });
          }

          log("INFO", "Invoking Bedrock Agent", {
            from: senderPhone,
            messageId: msg.id,
          });

          // Wrap in a labelled container so the model receives structural
          // context that this is customer-sourced data, not a system command.
          // This is a defence-in-depth measure against prompt injection;
          // the Bedrock Guardrail and agent instruction are the primary defences.
          const safeInput = `[Customer WhatsApp message from ${senderPhone}]\n${messageText}`;

          // Invoke Bedrock Agent and collect streaming reply
          const replyText = await invokeBedrockAgent(senderPhone, safeInput);

          log("INFO", "Bedrock Agent reply received", {
            from: senderPhone,
            replyLength: replyText.length,
          });

          // Send the reply back to the customer via EUMS
          await sendWhatsAppReply(senderPhone, replyText);

          log("INFO", "WhatsApp reply sent", { to: senderPhone });

          // Fire-and-forget log POST to OpenClaw for async record-keeping
          if (GATEWAY_URL) {
            postToGateway("/inbound/log", {
              from: senderPhone,
              text: messageText,
              reply: replyText,
              timestamp: msg.timestamp,
            }).catch((err: Error) => {
              log("WARN", "OpenClaw log POST failed (non-fatal)", {
                from: senderPhone,
                error: err.message,
              });
            });
          }
        }
      }

      // ── Delivery / read receipts (statuses) ─────────────────────────────
      if (value.statuses && value.statuses.length > 0) {
        log("INFO", "Routing WhatsApp delivery statuses", {
          count: value.statuses.length,
          phoneNumberId: value.metadata?.phone_number_id,
        });

        await postToGateway("/inbound/status", {
          source: "whatsapp",
          phoneNumberId: value.metadata?.phone_number_id,
          displayPhoneNumber: value.metadata?.display_phone_number,
          statuses: value.statuses,
        });
      }

      // Log if a change value carries neither messages nor statuses
      if (!value.messages?.length && !value.statuses?.length) {
        log("WARN", "WhatsApp change value has no messages or statuses", {
          field: change.field,
          valueKeys: Object.keys(value),
          messageId: record.Sns.MessageId,
        });
      }
    }
  }
}

// ---------------------------------------------------------------------------
// SNS source detection
// ---------------------------------------------------------------------------

/**
 * Determine whether this SNS record is a WhatsApp event from End User
 * Messaging Social. Uses subject, topic ARN, message attributes, and
 * payload-level heuristics.
 */
function isWhatsAppEvent(record: SNSEventRecord): boolean {
  const subject = record.Sns.Subject ?? "";
  const topicArn = record.Sns.TopicArn ?? "";
  const attrs = record.Sns.MessageAttributes ?? {};

  if (subject === "WhatsAppWebhookEvent") return true;

  if (
    topicArn.toLowerCase().includes("whatsapp") ||
    topicArn.toLowerCase().includes("endusermessaging") ||
    attrs["eventType"]?.Value === "WhatsAppWebhookEvent"
  ) {
    return true;
  }

  // Payload-level heuristic
  try {
    const parsed = JSON.parse(record.Sns.Message) as Record<string, unknown>;
    if ("whatsAppWebhookEntry" in parsed) return true;
  } catch {
    // ignore parse errors here; they'll be handled in the specific processor
  }

  return false;
}

// ---------------------------------------------------------------------------
// Main handler
// ---------------------------------------------------------------------------

export const handler = async (
  event: SNSEvent,
  _context: Context,
  _callback: Callback
): Promise<void> => {
  log("INFO", "Dispatcher invoked", {
    recordCount: event.Records.length,
  });

  // Process all records; errors in individual records are caught and logged
  // so they do not prevent other records in the same batch from being handled.
  const results = await Promise.allSettled(
    event.Records.map(async (record) => {
      const messageId = record.Sns.MessageId;

      log("INFO", "Processing SNS record", {
        messageId,
        topicArn: record.Sns.TopicArn,
        subject: record.Sns.Subject,
      });

      if (isWhatsAppEvent(record)) {
        await handleWhatsAppRecord(record);
      } else {
        log("WARN", "Non-WhatsApp event – record skipped", {
          messageId,
          subject: record.Sns.Subject,
          topicArn: record.Sns.TopicArn,
        });
      }
    })
  );

  // Surface any rejected promises as WARN (they were already ERROR-logged inside)
  let failureCount = 0;
  for (const result of results) {
    if (result.status === "rejected") {
      failureCount++;
      log("WARN", "Record processing promise rejected", {
        reason: String(result.reason),
      });
    }
  }

  log("INFO", "Dispatcher finished", {
    total: event.Records.length,
    succeeded: event.Records.length - failureCount,
    failed: failureCount,
  });

  // Do NOT throw – we don't want Lambda to retry the entire batch for a
  // partial failure.  Individual errors have been logged above.
};

// ---------------------------------------------------------------------------
// Example / test event
// ---------------------------------------------------------------------------
//
// Paste this into the Lambda console "Test" tab to simulate an End User
// Messaging Social WhatsApp inbound text message event.
//
// Structure reference:
//   https://docs.aws.amazon.com/social-messaging/latest/userguide/manage-event-subscriptions.html
//
// {
//   "Records": [
//     {
//       "EventVersion": "1.0",
//       "EventSubscriptionArn": "arn:aws:sns:us-east-1:123456789012:claw-boutique-whatsapp-topic:abc123",
//       "EventSource": "aws:sns",
//       "Sns": {
//         "SignatureVersion": "1",
//         "Timestamp": "2024-06-01T12:00:00.000Z",
//         "Signature": "EXAMPLE",
//         "SigningCertUrl": "https://sns.us-east-1.amazonaws.com/cert.pem",
//         "MessageId": "msg-uuid-0001",
//         "Message": "{\"whatsAppWebhookEntry\":\"{\\\"object\\\":\\\"whatsapp_business_account\\\",\\\"entry\\\":[{\\\"id\\\":\\\"WBA_ID_001\\\",\\\"changes\\\":[{\\\"value\\\":{\\\"messaging_product\\\":\\\"whatsapp\\\",\\\"metadata\\\":{\\\"display_phone_number\\\":\\\"+15550001234\\\",\\\"phone_number_id\\\":\\\"PN_ID_001\\\"},\\\"contacts\\\":[{\\\"profile\\\":{\\\"name\\\":\\\"Jane Doe\\\"},\\\"wa_id\\\":\\\"15559876543\\\"}],\\\"messages\\\":[{\\\"id\\\":\\\"wamid.ABC123\\\",\\\"from\\\":\\\"15559876543\\\",\\\"timestamp\\\":\\\"1717243200\\\",\\\"type\\\":\\\"text\\\",\\\"text\\\":{\\\"body\\\":\\\"Hello, I would like to book an appointment!\\\"}}]},\\\"field\\\":\\\"messages\\\"}]}]}\"}",
//         "Subject": "WhatsAppWebhookEvent",
//         "Type": "Notification",
//         "UnsubscribeUrl": "https://sns.us-east-1.amazonaws.com/?Action=Unsubscribe&SubscriptionArn=...",
//         "TopicArn": "arn:aws:sns:us-east-1:123456789012:claw-boutique-whatsapp-topic",
//         "MessageAttributes": {
//           "eventType": {
//             "Type": "String",
//             "Value": "WhatsAppWebhookEvent"
//           }
//         }
//       }
//     }
//   ]
// }
//
// Decoded inner payload (what's inside whatsAppWebhookEntry after JSON.parse):
// {
//   "object": "whatsapp_business_account",
//   "entry": [
//     {
//       "id": "WBA_ID_001",
//       "changes": [
//         {
//           "field": "messages",
//           "value": {
//             "messaging_product": "whatsapp",
//             "metadata": {
//               "display_phone_number": "+15550001234",
//               "phone_number_id": "PN_ID_001"
//             },
//             "contacts": [
//               { "profile": { "name": "Jane Doe" }, "wa_id": "15559876543" }
//             ],
//             "messages": [
//               {
//                 "id": "wamid.ABC123",
//                 "from": "15559876543",
//                 "timestamp": "1717243200",
//                 "type": "text",
//                 "text": { "body": "Hello, I would like to book an appointment!" }
//               }
//             ]
//           }
//         }
//       ]
//     }
//   ]
// }

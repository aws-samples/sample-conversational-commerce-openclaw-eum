/**
 * Claw Boutique – Lambda Dispatcher
 * ----------------------------------
 * Consumes SNS messages and routes inbound events to the OpenClaw gateway.
 *
 * Supported event types
 * ─────────────────────
 * 1. AWS End User Messaging Social (WhatsApp) events
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
 * 2. SES inbound email events
 *    Delivered via SES → S3/SQS → SNS.  The SNS `Message` field contains the
 *    SES notification JSON with `mail`, `receipt` and optionally `content`.
 *
 * Environment variables
 * ─────────────────────
 *   OPENCLAW_GATEWAY_URL   – Base HTTPS URL of the OpenClaw gateway
 *                            e.g. https://api.openclaw.example.com
 *   OPENCLAW_GATEWAY_TOKEN – Bearer token sent in every request
 */

import axios, { AxiosError } from "axios";
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

if (!GATEWAY_URL) {
  console.warn("[dispatcher] OPENCLAW_GATEWAY_URL is not set – all POSTs will fail");
}

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

async function postToGateway(path: string, body: unknown): Promise<void> {
  const url = `${GATEWAY_URL}${path}`;

  try {
    const response = await axios.post(url, body, {
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${GATEWAY_TOKEN}`,
      },
      timeout: 10_000, // 10 s – Lambda invocations are time-boxed
    });

    log("INFO", `POST ${path} succeeded`, {
      status: response.status,
      url,
    });
  } catch (err) {
    const axiosErr = err as AxiosError;
    log("ERROR", `POST ${path} failed`, {
      url,
      status: axiosErr.response?.status,
      responseBody: axiosErr.response?.data,
      errorMessage: axiosErr.message,
    });
    // Re-throw so the caller can decide whether to continue processing other records
    throw err;
  }
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
// SES email payload types
// ---------------------------------------------------------------------------

interface SesMailHeaders {
  name: string;
  value: string;
}

interface SesMail {
  source: string;
  destination: string[];
  messageId: string;
  commonHeaders: {
    from?: string[];
    to?: string[];
    subject?: string;
    date?: string;
    [key: string]: unknown;
  };
  headers: SesMailHeaders[];
}

interface SesReceipt {
  action: {
    type: string;
    bucketName?: string;
    objectKey?: string;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

interface SesNotification {
  notificationType: string;
  mail: SesMail;
  receipt: SesReceipt;
  content?: string; // raw email body if included
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
  let whatsAppPayload: WhatsAppWebhookPayload;
  try {
    whatsAppPayload = JSON.parse(outerEnvelope.whatsAppWebhookEntry) as WhatsAppWebhookPayload;
  } catch (err) {
    log("ERROR", "Failed to parse inner whatsAppWebhookEntry JSON", {
      messageId: record.Sns.MessageId,
      raw: outerEnvelope.whatsAppWebhookEntry.slice(0, 500),
    });
    return;
  }

  log("INFO", "Processing WhatsApp webhook payload", {
    messageId: record.Sns.MessageId,
    object: whatsAppPayload.object,
    entryCount: whatsAppPayload.entry?.length ?? 0,
  });

  // Iterate over all entries and their changes
  for (const entry of whatsAppPayload.entry ?? []) {
    for (const change of entry.changes ?? []) {
      const value = change.value;

      // ── Inbound messages (text, media, etc.) ────────────────────────────
      if (value.messages && value.messages.length > 0) {
        log("INFO", "Routing inbound WhatsApp messages", {
          count: value.messages.length,
          phoneNumberId: value.metadata?.phone_number_id,
        });

        await postToGateway("/inbound/whatsapp", {
          source: "whatsapp",
          phoneNumberId: value.metadata?.phone_number_id,
          displayPhoneNumber: value.metadata?.display_phone_number,
          contacts: value.contacts ?? [],
          messages: value.messages,
          rawEntry: entry,
        });
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

/**
 * Handles an SES inbound email SNS record.
 *
 * SES inbound email flow:
 *   SES receipt rule → S3 (store raw email) + SNS (notification)
 *
 * The SNS notification `Message` field contains a JSON-serialised
 * SesNotification object with `mail`, `receipt`, and (optionally) `content`.
 */
async function handleSesEmailRecord(record: SNSEventRecord): Promise<void> {
  const snsMessageRaw = record.Sns.Message;

  let sesNotification: SesNotification;
  try {
    sesNotification = JSON.parse(snsMessageRaw) as SesNotification;
  } catch (err) {
    log("ERROR", "Failed to parse SES notification JSON", {
      messageId: record.Sns.MessageId,
      raw: snsMessageRaw.slice(0, 500),
    });
    return;
  }

  const { mail, receipt, content } = sesNotification;

  const sender = mail.source;
  const subject = mail.commonHeaders?.subject ?? "(no subject)";
  const to = mail.destination ?? mail.commonHeaders?.to ?? [];

  // If the SES rule stored the email in S3, the object key is in receipt.action
  const s3BucketName = receipt.action?.bucketName;
  const s3ObjectKey = receipt.action?.objectKey;

  log("INFO", "Routing SES inbound email", {
    messageId: record.Sns.MessageId,
    sesMessageId: mail.messageId,
    sender,
    subject,
    hasInlineContent: Boolean(content),
    s3BucketName,
    s3ObjectKey,
  });

  await postToGateway("/inbound/email", {
    source: "email",
    messageId: mail.messageId,
    sender,
    to,
    subject,
    date: mail.commonHeaders?.date,
    headers: mail.headers,
    // Inline content is only present when the SES rule is configured to
    // include the raw email body in the notification (< 150 KB limit).
    // For larger emails, the gateway should fetch the object from S3.
    body: content ?? null,
    s3: s3BucketName && s3ObjectKey
      ? { bucket: s3BucketName, key: s3ObjectKey }
      : null,
    rawMail: mail,
  });
}

// ---------------------------------------------------------------------------
// SNS source detection
// ---------------------------------------------------------------------------

/**
 * Determine the event type from the SNS record metadata.
 *
 * End User Messaging Social sets a specific MessageAttribute or uses a
 * recognisable TopicArn / Subject prefix.  We use a combination of:
 *   1. `record.Sns.Subject` – EUMS sets this to a well-known value
 *   2. `record.Sns.MessageAttributes` – EUMS injects `eventType`
 *   3. Falling back to payload inspection (presence of `whatsAppWebhookEntry`)
 */
function detectEventType(record: SNSEventRecord): "whatsapp" | "ses" | "unknown" {
  const subject = record.Sns.Subject ?? "";
  const topicArn = record.Sns.TopicArn ?? "";
  const attrs = record.Sns.MessageAttributes ?? {};

  // End User Messaging Social publishes with this subject
  if (subject === "WhatsAppWebhookEvent") {
    return "whatsapp";
  }

  // Some deployments tag the topic ARN or inject a message attribute
  if (
    topicArn.toLowerCase().includes("whatsapp") ||
    topicArn.toLowerCase().includes("endusermessaging") ||
    attrs["eventType"]?.Value === "WhatsAppWebhookEvent"
  ) {
    return "whatsapp";
  }

  // SES notifications carry a `notificationType` field in the message body
  // and typically have a Subject like "Amazon SES Email Receipt Notification"
  if (subject.toLowerCase().includes("ses") || subject.toLowerCase().includes("email")) {
    return "ses";
  }

  // Payload-level heuristic – parse just enough to classify
  try {
    const parsed = JSON.parse(record.Sns.Message) as Record<string, unknown>;
    if ("whatsAppWebhookEntry" in parsed) return "whatsapp";
    if ("notificationType" in parsed && "mail" in parsed) return "ses";
  } catch {
    // ignore parse errors here; they'll be handled in the specific processor
  }

  return "unknown";
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
      const eventType = detectEventType(record);

      log("INFO", "Processing SNS record", {
        messageId,
        topicArn: record.Sns.TopicArn,
        subject: record.Sns.Subject,
        detectedType: eventType,
      });

      switch (eventType) {
        case "whatsapp":
          await handleWhatsAppRecord(record);
          break;

        case "ses":
          await handleSesEmailRecord(record);
          break;

        default:
          log("WARN", "Unknown event type – record skipped", {
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
//
// SES inbound email test event:
// {
//   "Records": [
//     {
//       "EventSource": "aws:sns",
//       "EventVersion": "1.0",
//       "EventSubscriptionArn": "arn:aws:sns:us-east-1:123456789012:claw-boutique-ses-topic:def456",
//       "Sns": {
//         "MessageId": "msg-uuid-0002",
//         "Subject": "Amazon SES Email Receipt Notification",
//         "TopicArn": "arn:aws:sns:us-east-1:123456789012:claw-boutique-ses-topic",
//         "Timestamp": "2024-06-01T12:05:00.000Z",
//         "Message": "{\"notificationType\":\"Received\",\"mail\":{\"source\":\"customer@example.com\",\"destination\":[\"hello@clawboutique.com\"],\"messageId\":\"ses-msg-001\",\"commonHeaders\":{\"from\":[\"Customer <customer@example.com>\"],\"to\":[\"hello@clawboutique.com\"],\"subject\":\"Appointment inquiry\",\"date\":\"Sat, 01 Jun 2024 12:05:00 +0000\"},\"headers\":[]},\"receipt\":{\"action\":{\"type\":\"S3\",\"bucketName\":\"claw-boutique-ses-inbox\",\"objectKey\":\"emails/ses-msg-001\"}},\"content\":null}",
//         "MessageAttributes": {},
//         "Type": "Notification",
//         "UnsubscribeUrl": "https://sns.us-east-1.amazonaws.com/?Action=Unsubscribe&...",
//         "SignatureVersion": "1",
//         "Signature": "EXAMPLE",
//         "SigningCertUrl": "https://sns.us-east-1.amazonaws.com/cert.pem"
//       }
//     }
//   ]
// }

#include <WiFi.h>
#include <WiFiUdp.h>
#include "Mona_ESP_lib.h"
#include <math.h>
#include <strings.h> // strncasecmp를 위한 헤더 추가 (Core 3.x 대응)

// ===================== WiFi / UDP =====================
const char* ssid     = "InMOLab";
const char* password = "dlsahfoq104!";
WiFiUDP udp;
const int localPort = 8080;
char packetBuffer[255];

// ===================== 배터리 전송 설정 =====================
const char*    BATT_PC_IP       = "192.168.0.21"; // listen_udp.py 실행 PC의 IP
const uint16_t BATT_UDP_PORT    = 5005;
static const unsigned long BATT_INTERVAL_MS = 500; // 3초마다 전송
static const unsigned long IDLE_SETTLE_MS   = 1000; // IDLE 진입 후 전압 안정화 대기
static unsigned long prev_batt_time = 0;
static unsigned long idle_since_ms  = 0;
static float batt_ema = -1.0f;
static const float EMA_ALPHA = 0.1f;

// ===================== 상태 정의 =====================
enum RobotState {
  STATE_IDLE,
  STATE_TURNING,
  STATE_MOVING,
  STATE_AVOID,
  STATE_ESCAPING,
  STATE_EMERGENCY
};
volatile RobotState state = STATE_IDLE;
static RobotState prev_loop_state = STATE_IDLE;

// 펄스/제어 상수
static const float PULSES_PER_MM     = 18.0f;
static const float PULSES_PER_DEGREE = 12.8f;
static const int   FWD_SPD  = 140;
static const int   TURN_SPD = 110;

// 900펄스마다 새로운 명령을 받음
static const long  UPDATE_THRESHOLD_PULSES = 1350;
static const float MIN_DIST_MM             = 10.0f;

// IR/회피
static const int TH        = 100;
static const int TH_OUTER  = 100;
static const int DELTA     = 15;

// 핀 번호 정의
static const int PIN_ENCODER_LEFT  = 35;
static const int PIN_ENCODER_RIGHT = 39;

// 제어 관련 임계값
static const float ROTATION_DEADBAND_DEG = 10.0f;
static const int   MIN_MOTOR_PWM         = 60;   // 60

// ===================== PI 제어 게인 =====================
// K_P: 누적 위치 오차(pulse) 1 당 PWM 보정량
//   너무 크면 사행(oscillation), 너무 작으면 수렴 느림
// K_I: 지속 편차(모터 특성 차이) 보정용. K_I × INTEGRAL_LIMIT = 최대 I 기여 PWM
//   0.01 × 500 = 5 PWM → 사실상 무의미했음. 0.08 × 150 = 12 PWM으로 의미 있는 보정
static const float K_P = 1.0f;    // 0.7→1.0: 위치 오차 수렴 속도 향상
static const float K_I = 0.08f;   // 0.01→0.08: I항이 실질적으로 기여하도록

// 적분 제한 (K_I × INTEGRAL_LIMIT = 최대 I 기여 PWM)
// 0.08 × 150 = 12 PWM → 지속 편차 보정에 충분, windup 방지
static const float INTEGRAL_LIMIT = 150.0f;  // 500→150

// 오차 데드밴드
static const int ERROR_DEADBAND = 5;

// 비상 동작 속도
static const int EMERGENCY_SPIN_SPD = 200;

static const uint16_t ESCAPING_MS = 500;
unsigned long escaping_until_ms = 0;

static const unsigned long EMERGENCY_SPIN_MS      = 1200;
static const unsigned long BACK_MS                = 120;
static const unsigned long OSCILLATION_WINDOW_MS  = 1200;
static const int   OSCILLATION_COUNT_THRESHOLD    = 4;

int last_turn_direction = 0;
int turn_change_count   = 0;
unsigned long oscillation_timer_start = 0;

unsigned long emergency_back_until = 0;
unsigned long emergency_spin_until = 0;

volatile long left_encoder_count  = 0;
volatile long right_encoder_count = 0;

void IRAM_ATTR isr_left_encoder()  { left_encoder_count++; }
void IRAM_ATTR isr_right_encoder() { right_encoder_count++; }

static long  start_left_count  = 0;
static long  start_right_count = 0;
static long  target_turn_pulses = 0;
static long  target_move_pulses = 0;
static float integral_error = 0.0f;

// ===================== 제어 주기 관리 =====================
static const unsigned long CONTROL_INTERVAL_MS = 5;
unsigned long last_control_time = 0;

// ===================== LED 상태 표시 =====================
static const unsigned long LED_UPDATE_INTERVAL_MS = 100;
unsigned long last_led_update = 0;

// ===================== 듀얼코어: 공유 자원 보호 =====================
// g_motor_mutex: 모터 함수 호출 및 공유 모션 변수(state, targets)를 보호
static SemaphoreHandle_t g_motor_mutex = NULL;

// IR 센싱 결과 (avoidTask → loop 가시성용, 인덱스 1~5 사용)
volatile int g_ir[6] = {};

// avoidTask 핸들
static TaskHandle_t avoidTaskHandle = NULL;

// ===================== 유틸리티 =====================
// 주의: 호출 전 g_motor_mutex를 반드시 획득해야 함
static inline void clear_motion_targets() {
  target_turn_pulses = 0;
  target_move_pulses = 0;
  start_left_count  = left_encoder_count;
  start_right_count = right_encoder_count;
  integral_error = 0.0f;
}

// 주의: 호출 전 g_motor_mutex를 반드시 획득해야 함
static inline void enter_escaping(uint16_t ms = ESCAPING_MS) {
  escaping_until_ms = millis() + ms;
  Motors_forward(FWD_SPD);
  state = STATE_ESCAPING;
}

// 주의: 호출 전 g_motor_mutex를 반드시 획득해야 함
static inline void start_emergency_left_spin() {
  unsigned long now = millis();
  emergency_back_until = now + BACK_MS;
  emergency_spin_until = emergency_back_until + EMERGENCY_SPIN_MS;

  Motors_backward(FWD_SPD);
  state = STATE_EMERGENCY;

  turn_change_count = 0;
  last_turn_direction = -1;
  oscillation_timer_start = now;

  Serial.println("[EMERGENCY] back -> spin_left");
}

// 주의: 호출 전 g_motor_mutex를 반드시 획득해야 함
static inline void check_oscillation_and_escape(int current_direction) {
  if (last_turn_direction != 0 && current_direction != last_turn_direction) {
    unsigned long now = millis();
    if (now - oscillation_timer_start > OSCILLATION_WINDOW_MS) {
      turn_change_count = 1;
      oscillation_timer_start = now;
    } else {
      turn_change_count++;
    }

    if (turn_change_count >= OSCILLATION_COUNT_THRESHOLD) {
      start_emergency_left_spin();
      return;
    }
  }
  last_turn_direction = current_direction;
}

// ===================== 개선된 PI 제어 =====================
void pi_control(long l_now, long r_now, int* left_pwm, int* right_pwm) {
  long err = l_now - r_now;
  if (abs(err) < ERROR_DEADBAND) {
    err = 0;
  }
  integral_error += (float)err;
  if (integral_error > INTEGRAL_LIMIT) integral_error = INTEGRAL_LIMIT;
  if (integral_error < -INTEGRAL_LIMIT) integral_error = -INTEGRAL_LIMIT;
  float u = (K_P * (float)err) + (K_I * integral_error);
  *left_pwm  = constrain((int)lroundf(FWD_SPD - u), MIN_MOTOR_PWM, 255);
  *right_pwm = constrain((int)lroundf(FWD_SPD + u), MIN_MOTOR_PWM, 255);
}

// ===================== LED 상태 표시 =====================
void update_status_led() {
  switch (state) {
    case STATE_IDLE:
      Set_LED(1, 0, 30, 0);   // 녹색: 대기
      Set_LED(2, 0, 30, 0);
      break;
    case STATE_TURNING:
      Set_LED(1, 0, 0, 50);   // 파란색: 회전
      Set_LED(2, 0, 0, 50);
      break;
    case STATE_MOVING:
      Set_LED(1, 30, 30, 30); // 흰색: 이동
      Set_LED(2, 30, 30, 30);
      break;
    case STATE_AVOID:
      Set_LED(1, 50, 50, 0);  // 노란색: 회피
      Set_LED(2, 50, 50, 0);
      break;
    case STATE_ESCAPING:
      Set_LED(1, 50, 25, 0);  // 주황색: 탈출
      Set_LED(2, 50, 25, 0);
      break;
    case STATE_EMERGENCY:
      Set_LED(1, 50, 0, 0);   // 빨간색: 비상
      Set_LED(2, 50, 0, 0);
      break;
  }
}

// ===================== 배터리 함수 =====================
float read_battery_percent() {
  const int SAMPLES = 200;
  long sum = 0;
  for (int i = 0; i < SAMPLES; i++) {
    sum += analogRead(Batt_Vol_pin);
  }
  float adc_avg = sum / (float)SAMPLES;
  float pct = (adc_avg - 2750) / 8.0f;
  return constrain(pct, 0.0f, 100.0f);
}

void send_battery() {
  float raw = read_battery_percent();

  // EMA 필터
  if (batt_ema < 0) batt_ema = raw;
  else batt_ema = EMA_ALPHA * raw + (1.0f - EMA_ALPHA) * batt_ema;

  long total_pulses = (left_encoder_count + right_encoder_count) / 2;

  Serial.printf("Battery: raw=%.1f%%  ema=%.1f%%  pulses=%ld\n", raw, batt_ema, total_pulses);

  char msg[64];
  snprintf(msg, sizeof(msg), "{\"battery\":%.1f,\"pulses\":%ld}", batt_ema, total_pulses);
  udp.beginPacket(BATT_PC_IP, BATT_UDP_PORT);
  udp.write((uint8_t*)msg, strlen(msg));
  udp.endPacket();
}

// ===================== 함수 선언 =====================
void start_motion(float angle_deg, float dist_mm);
void handle_udp_packet();
void control_loop_motion();

// ===================== Core 0: IR 읽기 + 회피 태스크 =====================
// - IR 센서 폴링 (5ms 주기)
// - STATE_AVOID / STATE_ESCAPING / STATE_EMERGENCY 처리
// - 모터 접근 시 g_motor_mutex 획득
void avoidTask(void* pvParam) {
  const TickType_t period = pdMS_TO_TICKS(5);
  TickType_t last_wake = xTaskGetTickCount();

  while (true) {
    // ── IR 센서 읽기 ──────────────────────────────────────
    int r1 = Get_IR(1), r2 = Get_IR(2), r3 = Get_IR(3),
        r4 = Get_IR(4), r5 = Get_IR(5);

    // loop()에서 참고할 수 있도록 공유 변수에 저장
    g_ir[1]=r1; g_ir[2]=r2; g_ir[3]=r3; g_ir[4]=r4; g_ir[5]=r5;

    bool obstacle = (r1>TH_OUTER)||(r2>TH)||(r3>TH)||(r4>TH)||(r5>TH_OUTER);

    // ── 1순위: 장애물 감지 → AVOID 진입 ─────────────────
    if (obstacle &&
        state != STATE_AVOID &&
        state != STATE_ESCAPING &&
        state != STATE_EMERGENCY) {
      xSemaphoreTake(g_motor_mutex, portMAX_DELAY);
      Motors_stop();
      clear_motion_targets();
      state = STATE_AVOID;
      xSemaphoreGive(g_motor_mutex);
    }

    // ── EMERGENCY 처리 ────────────────────────────────────
    if (state == STATE_EMERGENCY) {
      unsigned long now = millis();
      xSemaphoreTake(g_motor_mutex, portMAX_DELAY);
      if (now < emergency_back_until) {
        Motors_backward(FWD_SPD);
      } else if (now < emergency_spin_until) {
        Motors_spin_left(EMERGENCY_SPIN_SPD);
      } else {
        Motors_stop();
        state = STATE_IDLE;
      }
      xSemaphoreGive(g_motor_mutex);
      vTaskDelayUntil(&last_wake, period);
      continue;
    }

    // ── AVOID 처리 ────────────────────────────────────────
    if (state == STATE_AVOID) {
      xSemaphoreTake(g_motor_mutex, portMAX_DELAY);
      if ((r1<=TH_OUTER)&&(r2<=TH)&&(r3<=TH)&&(r4<=TH)&&(r5<=TH_OUTER)) {
        // 장애물 없어짐 → 탈출 직진
        enter_escaping(ESCAPING_MS);
      } else if (r3 >= TH) {
        if (abs(r2-r4)<=DELTA || r2<r4) {
          Motors_spin_left(TURN_SPD);
          check_oscillation_and_escape(-1);
        } else {
          Motors_spin_right(TURN_SPD);
          check_oscillation_and_escape(+1);
        }
      } else if (r1>=TH_OUTER || r2>=TH) {
        Motors_spin_right(TURN_SPD);
        check_oscillation_and_escape(+1);
      } else if (r4>=TH || r5>=TH_OUTER) {
        Motors_spin_left(TURN_SPD);
        check_oscillation_and_escape(-1);
      }
      xSemaphoreGive(g_motor_mutex);
      vTaskDelayUntil(&last_wake, period);
      continue;
    }

    // ── ESCAPING 처리 ─────────────────────────────────────
    if (state == STATE_ESCAPING) {
      // 직진 중 새 장애물 감지 → 즉시 AVOID로 복귀 (타이머는 유지)
      if (obstacle) {
        xSemaphoreTake(g_motor_mutex, portMAX_DELAY);
        Motors_stop();
        clear_motion_targets();
        state = STATE_AVOID;
        xSemaphoreGive(g_motor_mutex);
        vTaskDelayUntil(&last_wake, period);
        continue;
      }
      // 1000ms 경과 → 완료
      if ((int32_t)(millis() - escaping_until_ms) >= 0) {
        xSemaphoreTake(g_motor_mutex, portMAX_DELAY);
        Motors_stop();
        state = STATE_IDLE;
        xSemaphoreGive(g_motor_mutex);
      }
      vTaskDelayUntil(&last_wake, period);
      continue;
    }

    vTaskDelayUntil(&last_wake, period);
  }
}

// ===================== setup =====================
void setup() {
  Serial.begin(115200);
  Mona_ESP_init();

  pinMode(PIN_ENCODER_LEFT, INPUT);
  pinMode(PIN_ENCODER_RIGHT, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_ENCODER_LEFT), isr_left_encoder,  RISING);
  attachInterrupt(digitalPinToInterrupt(PIN_ENCODER_RIGHT), isr_right_encoder, RISING);

  // WiFi 연결
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500); Serial.print(".");
  }
  Serial.println("\nWiFi connected");
  Serial.println(WiFi.localIP());

  udp.begin(localPort);
  Set_LED(1, 0, 30, 0);
  Set_LED(2, 0, 30, 0);

  // 시작 시 즉시 배터리 전송
  send_battery();
  prev_batt_time = millis();

  // ── 듀얼코어 초기화 ────────────────────────────────────
  g_motor_mutex = xSemaphoreCreateMutex();

  // avoidTask: Core 0, 우선순위 2 (loop의 기본 1보다 높게 설정)
  xTaskCreatePinnedToCore(
    avoidTask,       // 함수
    "avoidTask",     // 이름
    4096,            // 스택 크기 (bytes)
    NULL,            // 파라미터
    2,               // 우선순위
    &avoidTaskHandle,
    0                // Core 0
  );

  Serial.println("MONA ready puppet! (dual-core)");
}

// ===================== Core 1: 메인 루프 =====================
// - UDP 패킷 처리
// - 배터리 전송
// - STATE_TURNING / STATE_MOVING 모션 제어
// - LED 업데이트
void loop() {
  unsigned long now = millis();

  // IDLE 진입 시점 추적
  if (state == STATE_IDLE && prev_loop_state != STATE_IDLE) {
    idle_since_ms = now;
  }
  prev_loop_state = state;

  // 배터리 주기 전송 (3초, IDLE 진입 후 1000ms 안정화 후)
  if (now - prev_batt_time >= BATT_INTERVAL_MS) {
    if (state == STATE_IDLE && (now - idle_since_ms >= IDLE_SETTLE_MS)) {
      send_battery();
    }
    prev_batt_time = now;
  }

  // UDP 패킷 처리
  handle_udp_packet();

  // 모션 제어 (5ms 주기, TURNING/MOVING 상태만)
  if (now - last_control_time >= CONTROL_INTERVAL_MS) {
    last_control_time = now;
    if (state == STATE_TURNING || state == STATE_MOVING) {
      control_loop_motion();
    }
  }

  // LED 업데이트 (100ms 주기)
  if (now - last_led_update >= LED_UPDATE_INTERVAL_MS) {
    last_led_update = now;
    update_status_led();
  }
}

// ===================== 모션 시작 =====================
void start_motion(float angle_deg, float dist_mm) {
  xSemaphoreTake(g_motor_mutex, portMAX_DELAY);

  // 회피 기동 중에는 명령 무시
  if (state == STATE_AVOID || state == STATE_ESCAPING || state == STATE_EMERGENCY) {
    xSemaphoreGive(g_motor_mutex);
    return;
  }

  start_left_count  = left_encoder_count;
  start_right_count = right_encoder_count;
  integral_error = 0.0f;

  target_turn_pulses = (long)lroundf(fabsf(angle_deg) * PULSES_PER_DEGREE);
  target_move_pulses = (long)lroundf(fabsf(dist_mm)  * PULSES_PER_MM);

  if (target_turn_pulses > 0 && fabsf(angle_deg) > ROTATION_DEADBAND_DEG) {
    state = STATE_TURNING;
    if (angle_deg > 0) Motors_spin_right(TURN_SPD);
    else                Motors_spin_left(TURN_SPD);
  } else if (target_move_pulses > 0) {
    state = STATE_MOVING;
  } else {
    state = STATE_IDLE;
    Motors_stop();
  }

  xSemaphoreGive(g_motor_mutex);
}

// ===================== UDP 패킷 처리 =====================
void handle_udp_packet() {
  int packetSize = udp.parsePacket();
  if (!packetSize) return;

  // 버퍼 플러시
  while (packetSize) {
    int len = udp.read(packetBuffer, 255);
    if (len > 0) packetBuffer[len] = 0;
    packetSize = udp.parsePacket();
  }

  if (strncasecmp(packetBuffer, "STOP", 4) == 0) {
    xSemaphoreTake(g_motor_mutex, portMAX_DELAY);
    // 회피 기동 중에는 STOP 무시
    if (state == STATE_AVOID || state == STATE_ESCAPING || state == STATE_EMERGENCY) {
      xSemaphoreGive(g_motor_mutex);
      return;
    }
    Motors_stop();
    clear_motion_targets();
    state = STATE_IDLE;
    xSemaphoreGive(g_motor_mutex);
    return;
  }

  if (packetBuffer[0] == 'G' || packetBuffer[0] == 'g') {
    float angle = 0, dist = 0;
    if (sscanf(packetBuffer + 1, "%f %f", &angle, &dist) == 2) {
      if (dist < MIN_DIST_MM) return;

      if (state == STATE_MOVING) {
        long l_now = labs(left_encoder_count - start_left_count);
        long r_now = labs(right_encoder_count - start_right_count);
        if (((l_now + r_now) / 2) < UPDATE_THRESHOLD_PULSES) return;
      }
      start_motion(angle, dist);
    }
  }
}

// ===================== Core 1 모션 제어 (TURNING / MOVING) =====================
// STATE_AVOID / ESCAPING / EMERGENCY 는 avoidTask(Core 0)에서 처리
void control_loop_motion() {
  xSemaphoreTake(g_motor_mutex, portMAX_DELAY);

  long l_now = labs(left_encoder_count - start_left_count);
  long r_now = labs(right_encoder_count - start_right_count);
  long avg   = (l_now + r_now) / 2;

  switch (state) {
    case STATE_TURNING:
      if (avg >= target_turn_pulses) {
        Motors_stop();
        if (target_move_pulses > 0) {
          start_left_count  = left_encoder_count;
          start_right_count = right_encoder_count;
          integral_error = 0.0f;
          state = STATE_MOVING;
        } else {
          state = STATE_IDLE;
        }
      }
      break;

    case STATE_MOVING:
      if (avg >= target_move_pulses) {
        Motors_stop();
        state = STATE_IDLE;
      } else {
        int left_pwm, right_pwm;
        pi_control(l_now, r_now, &left_pwm, &right_pwm);
        Left_mot_forward(left_pwm);
        Right_mot_forward(right_pwm);
      }
      break;

    default:
      break;
  }

  xSemaphoreGive(g_motor_mutex);
}
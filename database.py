"""
Database Manager for Datasheet Analyzer
SQLite를 사용한 분석 결과 저장 및 관리
"""

import sqlite3
import json
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path


class DatasheetDatabase:
    """데이터시트 분석 결과 데이터베이스 매니저"""

    def __init__(self, db_path: str = "datasheet_analyzer.db"):
        """
        데이터베이스 초기화

        Args:
            db_path: 데이터베이스 파일 경로
        """
        self.db_path = db_path
        self.init_database()

    def get_connection(self) -> sqlite3.Connection:
        """데이터베이스 연결 생성"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # 딕셔너리처럼 접근 가능
        return conn

    def init_database(self):
        """데이터베이스 테이블 초기화"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 데이터시트 분석 결과 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS datasheet_analysis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT NOT NULL,
                vendor_code TEXT,
                analysis_result TEXT NOT NULL,
                file_hash TEXT,
                status TEXT DEFAULT 'Finish',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(filename, file_hash)
            )
        ''')

        # 마이그레이션: part_number 컬럼 제거 (있으면)
        try:
            # 테이블 정보 확인
            cursor.execute("PRAGMA table_info(datasheet_analysis)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'part_number' in columns:
                # part_number 컬럼이 있으면 테이블 재생성
                print("마이그레이션: part_number 컬럼 제거 중...")

                # 임시 테이블 생성
                cursor.execute('''
                    CREATE TABLE datasheet_analysis_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        filename TEXT NOT NULL,
                        vendor_code TEXT,
                        analysis_result TEXT NOT NULL,
                        file_hash TEXT,
                        status TEXT DEFAULT 'Finish',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(filename, file_hash)
                    )
                ''')

                # 데이터 복사
                cursor.execute('''
                    INSERT INTO datasheet_analysis_new
                    (id, filename, vendor_code, analysis_result, file_hash, status, created_at, updated_at)
                    SELECT id, filename, vendor_code, analysis_result, file_hash, status, created_at, updated_at
                    FROM datasheet_analysis
                ''')

                # 기존 테이블 삭제
                cursor.execute('DROP TABLE datasheet_analysis')

                # 새 테이블 이름 변경
                cursor.execute('ALTER TABLE datasheet_analysis_new RENAME TO datasheet_analysis')

                print("마이그레이션 완료!")
        except Exception as e:
            print(f"마이그레이션 오류 (무시 가능): {e}")

        # 분석 메타데이터 테이블 (추가 정보)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS analysis_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                datasheet_id INTEGER NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                FOREIGN KEY (datasheet_id) REFERENCES datasheet_analysis(id) ON DELETE CASCADE,
                UNIQUE(datasheet_id, key)
            )
        ''')

        # 체크포인트 테이블
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS checkpoint (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                datasheet_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                python_code TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (datasheet_id) REFERENCES datasheet_analysis(id) ON DELETE CASCADE
            )
        ''')

        # 인덱스 생성
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_filename
            ON datasheet_analysis(filename)
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_vendor_code
            ON datasheet_analysis(vendor_code)
        ''')

        conn.commit()
        conn.close()

    def insert_analysis(
        self,
        filename: str,
        analysis_result: str,
        vendor_code: Optional[str] = None,
        file_hash: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        분석 결과 저장

        Args:
            filename: 데이터시트 파일명
            analysis_result: AI 분석 결과 (텍스트)
            vendor_code: 벤더 코드
            file_hash: 파일 해시값 (중복 방지용)
            metadata: 추가 메타데이터 (딕셔너리)

        Returns:
            생성된 레코드 ID
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO datasheet_analysis
                (filename, vendor_code, analysis_result, file_hash)
                VALUES (?, ?, ?, ?)
            ''', (filename, vendor_code, analysis_result, file_hash))

            datasheet_id = cursor.lastrowid

            # 메타데이터 저장
            if metadata:
                for key, value in metadata.items():
                    cursor.execute('''
                        INSERT INTO analysis_metadata (datasheet_id, key, value)
                        VALUES (?, ?, ?)
                    ''', (datasheet_id, key, json.dumps(value) if isinstance(value, (dict, list)) else str(value)))

            conn.commit()
            return datasheet_id

        except sqlite3.IntegrityError as e:
            conn.rollback()
            raise ValueError(f"중복된 데이터: {e}")
        finally:
            conn.close()

    def update_analysis(
        self,
        analysis_id: int,
        analysis_result: Optional[str] = None,
        vendor_code: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        분석 결과 업데이트

        Args:
            analysis_id: 업데이트할 레코드 ID
            analysis_result: 새로운 분석 결과
            vendor_code: 새로운 벤더 코드
            metadata: 업데이트할 메타데이터
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            updates = []
            params = []

            if analysis_result is not None:
                updates.append("analysis_result = ?")
                params.append(analysis_result)

            if vendor_code is not None:
                updates.append("vendor_code = ?")
                params.append(vendor_code)

            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(analysis_id)

            if updates:
                cursor.execute(f'''
                    UPDATE datasheet_analysis
                    SET {", ".join(updates)}
                    WHERE id = ?
                ''', params)

            # 메타데이터 업데이트
            if metadata:
                for key, value in metadata.items():
                    cursor.execute('''
                        INSERT OR REPLACE INTO analysis_metadata (datasheet_id, key, value)
                        VALUES (?, ?, ?)
                    ''', (analysis_id, key, json.dumps(value) if isinstance(value, (dict, list)) else str(value)))

            conn.commit()

        finally:
            conn.close()

    def get_analysis_by_id(self, analysis_id: int) -> Optional[Dict[str, Any]]:
        """ID로 분석 결과 조회"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM datasheet_analysis WHERE id = ?
        ''', (analysis_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

    def get_analysis_by_filename(self, filename: str) -> Optional[Dict[str, Any]]:
        """파일명으로 분석 결과 조회 (가장 최근 결과)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM datasheet_analysis
            WHERE filename = ?
            ORDER BY created_at DESC
            LIMIT 1
        ''', (filename,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

    def search_by_vendor(self, vendor_code: str) -> List[Dict[str, Any]]:
        """벤더 코드로 검색"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM datasheet_analysis
            WHERE vendor_code LIKE ?
            ORDER BY created_at DESC
        ''', (f'%{vendor_code}%',))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]


    def get_all_analysis(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """모든 분석 결과 조회 (페이징)"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM datasheet_analysis
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        ''', (limit, offset))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def delete_analysis(self, analysis_id: int):
        """분석 결과 삭제"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM datasheet_analysis WHERE id = ?
        ''', (analysis_id,))

        conn.commit()
        conn.close()

    def get_metadata(self, datasheet_id: int) -> Dict[str, Any]:
        """특정 데이터시트의 메타데이터 조회"""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT key, value FROM analysis_metadata
            WHERE datasheet_id = ?
        ''', (datasheet_id,))

        rows = cursor.fetchall()
        conn.close()

        metadata = {}
        for row in rows:
            key = row['key']
            value = row['value']

            # JSON 파싱 시도
            try:
                metadata[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                metadata[key] = value

        return metadata

    def get_statistics(self) -> Dict[str, Any]:
        """통계 정보 조회"""
        conn = self.get_connection()
        cursor = conn.cursor()

        # 전체 분석 개수
        cursor.execute('SELECT COUNT(*) as total FROM datasheet_analysis')
        total = cursor.fetchone()['total']

        # 벤더별 개수
        cursor.execute('''
            SELECT vendor_code, COUNT(*) as count
            FROM datasheet_analysis
            WHERE vendor_code IS NOT NULL
            GROUP BY vendor_code
            ORDER BY count DESC
            LIMIT 10
        ''')
        vendor_stats = [dict(row) for row in cursor.fetchall()]

        # 최근 분석 날짜
        cursor.execute('''
            SELECT MAX(created_at) as latest_analysis
            FROM datasheet_analysis
        ''')
        latest = cursor.fetchone()['latest_analysis']

        conn.close()

        return {
            'total_analysis': total,
            'vendor_stats': vendor_stats,
            'latest_analysis': latest
        }

    # ========================================================================
    # Checkpoint 관련 메서드
    # ========================================================================

    def insert_checkpoint(
        self,
        datasheet_id: int,
        text: str,
        python_code: str
    ) -> int:
        """
        체크포인트 저장

        Args:
            datasheet_id: 데이터시트 분석 ID (외래키)
            text: 텍스트 내용
            python_code: 파이썬 코드

        Returns:
            생성된 체크포인트 ID
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                INSERT INTO checkpoint (datasheet_id, text, python_code)
                VALUES (?, ?, ?)
            ''', (datasheet_id, text, python_code))

            checkpoint_id = cursor.lastrowid
            conn.commit()
            return checkpoint_id

        finally:
            conn.close()

    def get_checkpoints_by_datasheet(self, datasheet_id: int) -> List[Dict[str, Any]]:
        """
        특정 데이터시트의 모든 체크포인트 조회

        Args:
            datasheet_id: 데이터시트 분석 ID

        Returns:
            체크포인트 리스트
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM checkpoint
            WHERE datasheet_id = ?
            ORDER BY created_at ASC
        ''', (datasheet_id,))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]

    def get_checkpoint_by_id(self, checkpoint_id: int) -> Optional[Dict[str, Any]]:
        """
        ID로 체크포인트 조회

        Args:
            checkpoint_id: 체크포인트 ID

        Returns:
            체크포인트 정보
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM checkpoint WHERE id = ?
        ''', (checkpoint_id,))

        row = cursor.fetchone()
        conn.close()

        if row:
            return dict(row)
        return None

    def update_checkpoint(
        self,
        checkpoint_id: int,
        text: Optional[str] = None,
        python_code: Optional[str] = None
    ):
        """
        체크포인트 업데이트

        Args:
            checkpoint_id: 업데이트할 체크포인트 ID
            text: 새로운 텍스트 내용
            python_code: 새로운 파이썬 코드
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            updates = []
            params = []

            if text is not None:
                updates.append("text = ?")
                params.append(text)

            if python_code is not None:
                updates.append("python_code = ?")
                params.append(python_code)

            if updates:
                params.append(checkpoint_id)
                cursor.execute(f'''
                    UPDATE checkpoint
                    SET {", ".join(updates)}
                    WHERE id = ?
                ''', params)

                conn.commit()

        finally:
            conn.close()

    def delete_checkpoint(self, checkpoint_id: int):
        """
        체크포인트 삭제

        Args:
            checkpoint_id: 삭제할 체크포인트 ID
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM checkpoint WHERE id = ?
        ''', (checkpoint_id,))

        conn.commit()
        conn.close()

    def delete_checkpoints_by_datasheet(self, datasheet_id: int):
        """
        특정 데이터시트의 모든 체크포인트 삭제

        Args:
            datasheet_id: 데이터시트 분석 ID
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            DELETE FROM checkpoint WHERE datasheet_id = ?
        ''', (datasheet_id,))

        conn.commit()
        conn.close()


def calculate_file_hash(file_path: str) -> str:
    """파일 해시 계산 (중복 방지용)"""
    import hashlib

    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

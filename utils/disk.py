import gzip

from diskcache import FanoutCache, Disk, core
from diskcache.core import io
from io import BytesIO
from diskcache.core import MODE_BINARY
from cassandra.cqltypes import BytesType

from util.logconf import logging

log = logging.getLogger(__name__)
# log.setLevel(logging.WARN)  # ログレベルを WARNING に設定（コメントアウト状態）
log.setLevel(logging.INFO)  # ログレベルを INFO に設定
# log.setLevel(logging.DEBUG) # ログレベルを DEBUG に設定（コメントアウト状態）


class GzipDisk(Disk):
    """
    ディスクキャッシュの保存・取得時に gzip 圧縮/解凍を行うカスタム Disk クラス。
    大容量データを分割して処理することで、古い Python バージョンでの zlib バッファ制限問題に対応している。
    """

    def store(self, value, read, key=None):
        """
        値を gzip 圧縮してディスクに保存する処理をオーバーライド。
        Python < 2.7.13 の zlib バッファ制限（2〜4GiB問題）に対応するため、1GiB 単位で分割して書き込む。

        :param value: 保存する値
        :param bool read: True の場合は value がファイルオブジェクト
        :param key: キャッシュキー（未使用）
        :return: (size, mode, filename, value) のタプル（親クラスの戻り値）
        """
        # pylint: disable=unidiomatic-typecheck
        if type(value) is BytesType:
            if read:
                # ファイルオブジェクトからデータを読み込む
                value = value.read()
                read = False

            # メモリ上に gzip 圧縮データを書き込むためのバッファ
            str_io = BytesIO()
            gz_file = gzip.GzipFile(mode="wb", compresslevel=1, fileobj=str_io)

            # 1 GiB ごとに分割して書き込み
            for offset in range(0, len(value), 2**30):
                gz_file.write(value[offset : offset + 2**30])
            gz_file.close()

            # 圧縮データを取得
            value = str_io.getvalue()

        # 親クラスの store を呼び出して保存
        return super(GzipDisk, self).store(value, read)

    def fetch(self, mode, filename, value, read):
        """
        ディスクから gzip 圧縮されたデータを読み込み、解凍する処理をオーバーライド。

        :param int mode: モード（raw, binary, text, pickle など）
        :param str filename: 保存ファイル名
        :param value: データベース上の値
        :param bool read: True の場合はファイルハンドルを返す
        :return: 解凍後の Python オブジェクト
        """
        # 親クラスの fetch でデータを取得
        value = super(GzipDisk, self).fetch(mode, filename, value, read)

        # バイナリモードの場合のみ gzip 解凍
        if mode == MODE_BINARY:
            str_io = BytesIO(value)
            gz_file = gzip.GzipFile(mode="rb", fileobj=str_io)
            read_csio = BytesIO()

            # 1 GiB ごとに読み込み・解凍
            while True:
                uncompressed_data = gz_file.read(2**30)
                if uncompressed_data:
                    read_csio.write(uncompressed_data)
                else:
                    break

            # 解凍したデータを取得
            value = read_csio.getvalue()

        return value


def getCache(scope_str):
    """
    圧縮ディスクキャッシュを取得するユーティリティ関数。

    :param scope_str: キャッシュのスコープ名（保存先ディレクトリ名に使用）
    :return: FanoutCache オブジェクト
    """
    return FanoutCache(
        "data-unversioned/cache/" + scope_str,  # キャッシュ保存先ディレクトリ
        disk=GzipDisk,  # gzip 対応ディスククラスを使用
        shards=64,  # 分割数（並列アクセス用）
        timeout=1,  # ロックタイムアウト（秒）
        size_limit=3e11,  # キャッシュサイズ上限（300GB）
        # disk_min_file_size=2**20,  # 最小ファイルサイズ（コメントアウト）
    )


# 以下は gzip 圧縮付きの pickle キャッシュを作成するためのデコレータ群（コメントアウト）
# def disk_cache(base_path, memsize=2):
#     def disk_cache_decorator(f):
#         @functools.wraps(f)
#         def wrapper(*args, **kwargs):
#             args_str = repr(args) + repr(sorted(kwargs.items()))
#             file_str = hashlib.md5(args_str.encode('utf8')).hexdigest()
#
#             cache_path = os.path.join(base_path, f.__name__, file_str + '.pkl.gz')
#
#             if not os.path.exists(os.path.dirname(cache_path)):
#                 os.makedirs(os.path.dirname(cache_path), exist_ok=True)
#
#             if os.path.exists(cache_path):
#                 return pickle_loadgz(cache_path)
#             else:
#                 ret = f(*args, **kwargs)
#                 pickle_dumpgz(cache_path, ret)
#                 return ret
#
#         return wrapper
#
#     return disk_cache_decorator
#
#
# def pickle_dumpgz(file_path, obj):
#     log.debug("Writing {}".format(file_path))
#     with open(file_path, 'wb') as file_obj:
#         with gzip.GzipFile(mode='wb', compresslevel=1, fileobj=file_obj) as gz_file:
#             pickle.dump(obj, gz_file, pickle.HIGHEST_PROTOCOL)
#
#
# def pickle_loadgz(file_path):
#     log.debug("Reading {}".format(file_path))
#     with open(file_path, 'rb') as file_obj:
#         with gzip.GzipFile(mode='rb', fileobj=file_obj) as gz_file:
#             return pickle.load(gz_file)
#
#
# def dtpath(dt=None):
#     if dt is None:
#         dt = datetime.datetime.now()
#
#     return str(dt).rsplit('.', 1)[0].replace(' ', '--').replace(':', '.')
#
#
# def safepath(s):
#     s = s.replace(' ', '_')
#     return re.sub('[^A-Za-z0-9_.-]', '', s)

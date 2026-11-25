/* SPDX-License-Identifier: GPL-2.0-only */
#define main sft_viewer_main
#include SFT_TEST_VIEWER_SOURCE
#undef main
#include <assert.h>

static unsigned feed(sft_hdr_t header, unsigned bytes, int sleeping)
{
    g_in=tmpfile(); assert(g_in);
    fwrite(&header,1,sizeof(header),g_in);
    unsigned char zeros[128]={0};
    assert(bytes<=sizeof(zeros)); fwrite(zeros,1,bytes,g_in); rewind(g_in);
    g_quit=0; g_lost=0; g_rd_stop=0; g_qh=g_qn=0;
    SDL_AtomicSet(&pi_economy_active,sleeping);
    unsigned before=(unsigned)SDL_AtomicGet(&pi_media_serial);
    reader_main(NULL);
    unsigned activity=(unsigned)SDL_AtomicGet(&pi_media_serial)-before;
    fclose(g_in); g_in=NULL; g_quit=0;
    if (sleeping) assert(g_qn==0);
    return activity;
}

int main(void)
{
    SDL_setenv("SDL_VIDEODRIVER", "dummy", 1);
    SDL_setenv("SDL_AUDIODRIVER", "dummy", 1);
    SDL_setenv("SFT_IDLE_TIMEOUT", "1", 1);
    assert(SDL_Init(SDL_INIT_VIDEO) == 0);
    g_app = 1; g_hwdec = 1; g_conn = CONN_USB;
    pi_idle_init(1);
    assert(pi_idle.timeout_ms == 1000);
    pi_idle.timeout_ms = 1; /* Exercise the same boundary without waiting 20 minutes. */
    SDL_Window *window = SDL_CreateWindow("idle lifecycle",0,0,640,360,0);
    assert(window);
    SDL_Renderer *renderer = SDL_CreateRenderer(window,-1,SDL_RENDERER_SOFTWARE);
    assert(renderer);
    g_paint_win = window; g_paint_ren = renderer;
    g_qm = SDL_CreateMutex(); g_q_get = SDL_CreateCond(); g_q_put = SDL_CreateCond();
    g_tx_m = SDL_CreateMutex();
    sft_hdr_t header={ .magic=SFT_MAGIC, .version=1, .flags=SFT_FLAG_AUDIO|SFT_FLAG_STATUS, .length=12 };
    assert(feed(header,12,1)==0); /* status does not reset or wake */
    header.flags=SFT_FLAG_H264; header.width=1920; header.height=1080; header.stride=900000;
    assert(feed(header,12,1)==0); /* stale frames do not fill the queue */
    header.stride=20000;
    assert(feed(header,12,1)==1); /* fresh video wakes with USB still present */
    assert(feed(header,4,1)==0);  /* truncated media never wakes */
    header.flags=SFT_FLAG_AUDIO; header.width=44100; header.height=2; header.stride=0;
    assert(feed(header,12,1)==0); /* unsupported audio is not activity */
    header.width=48000; g_mute=1;
    assert(feed(header,12,1)==1); /* valid audio wakes even when muted */
    g_mute=0; g_qh=g_qn=0; SDL_AtomicSet(&pi_economy_active,0);
    g_fm = SDL_CreateMutex(); g_f_put = SDL_CreateCond();
    for (int i=0;i<FQ;i++) { g_fq[i]=av_frame_alloc(); assert(g_fq[i]); }
    h264_t dec={0};
    assert(h264_open(&dec,1,1,g_hwdec)==0);
    assert(is_v4l2_decoder(&dec));
    pi_audio_open(); assert(g_adev);
    dec_args_t args={ &dec, NULL, NULL };
    SDL_Thread *thread=SDL_CreateThread(decoder_main,"decoder",&args);
    assert(thread);
    SDL_Texture *texture=NULL;
    AVFrame *show=av_frame_alloc(); assert(show);
    uint32_t width=0,height=0;
    pi_idle_live live={ &dec,&thread,&args,show,&texture,&renderer,&width,&height,0 };
    pi_idle_resources=pi_idle_live_transition; pi_idle_opaque=&live;
    pi_idle.media_serial=(uint32_t)SDL_AtomicGet(&pi_media_serial);
    for (int i=0;i<20;i++) {
        if (i==10) {
            SDL_DestroyRenderer(renderer);
            renderer=SDL_CreateRenderer(window,-1,SDL_RENDERER_SOFTWARE);
            assert(renderer); g_paint_ren=renderer;
        }
        AVBufferRef *held=av_buffer_alloc(16); assert(held);
        show->buf[0]=av_buffer_ref(held);
        g_fq[0]->buf[0]=av_buffer_ref(held); g_fh=0; g_fn=1;
        width=640; height=360;
        texture=SDL_CreateTexture(renderer,SDL_PIXELFORMAT_ARGB8888,SDL_TEXTUREACCESS_STREAMING,640,360);
        assert(texture); g_paint_tex=texture;
        pi_idle.last_media_ms=SDL_GetTicks64();
        SDL_Delay(3);
        pi_idle_tick(1);
        assert(pi_idle.sleeping && live.suspended);
        assert(!dec.c && !thread && !g_adev && !g_fn);
        assert(!texture && !g_paint_tex && !width && !height);
        assert(av_buffer_get_ref_count(held)==1); av_buffer_unref(&held);
        assert(!(SDL_WasInit(SDL_INIT_AUDIO)&SDL_INIT_AUDIO));
        pi_idle_media(); /* USB transport remains present: no re-enumeration needed. */
        pi_idle_tick(1);
        assert(!pi_idle.sleeping && !live.suspended);
        assert(dec.c && thread && g_adev);
        assert(is_v4l2_decoder(&dec));
    }
    pi_idle_live_transition(1,&live);
    pi_idle_resources=NULL; pi_idle_opaque=NULL;
    assert(!dec.c && !thread && !g_adev);
    for(int i=0;i<FQ;i++) av_frame_free(&g_fq[i]);
    av_frame_free(&show);
    SDL_DestroyRenderer(renderer); SDL_DestroyWindow(window); SDL_Quit();
    puts("idle lifecycle: 20 V4L2/audio release/resume cycles without USB replug PASS");
    puts("reader: status, stale/truncated media, fresh video and muted audio PASS");
    return 0;
}
